#!/usr/bin/env python3

import argparse
import json
import logging
import sys

from argparse import ArgumentParser
from mozapkpublisher.common import googleplay, store_l10n
from mozapkpublisher.common.apk import extractor, checker
from mozapkpublisher.common.exceptions import WrongArgumentGiven
from mozapkpublisher.update_apk_description import create_or_update_listings

logger = logging.getLogger(__name__)


def push_apk(apks, service_account, google_play_credentials_file, track, update_google_play_strings=True,
             update_google_play_strings_from_store=False, google_play_strings_file=None, rollout_percentage=None,
             commit=True, contact_google_play=True):
    if track == 'rollout' and rollout_percentage is None:
        raise WrongArgumentGiven("When using track='rollout', rollout percentage must be provided too")
    if rollout_percentage is not None and track != 'rollout':
        raise WrongArgumentGiven("When using rollout-percentage, track must be set to rollout")

    PushAPK(apks, service_account, google_play_credentials_file, track, update_google_play_strings,
            update_google_play_strings_from_store, google_play_strings_file, rollout_percentage, commit,
            contact_google_play).run()


class PushAPK:
    def __init__(self, apks, service_account, google_play_credentials_file, track, update_google_play_strings,
                 update_google_play_strings_from_store, google_play_strings_file, rollout_percentage, commit,
                 contact_google_play):
        self.apks = apks
        self.service_account = service_account
        self.google_play_credentials_file = google_play_credentials_file
        self.track = track
        self.update_google_play_strings = update_google_play_strings
        self.update_google_play_strings_from_store = update_google_play_strings_from_store
        self.google_play_strings_file = google_play_strings_file
        self.rollout_percentage = rollout_percentage
        self.commit = commit
        self.contact_google_play = contact_google_play

    def upload_apks(self, apks_metadata_per_paths, package_name, l10n_strings=None):
        edit_service = googleplay.EditService(
            self.service_account, self.google_play_credentials_file.name, package_name,
            commit=self.commit, contact_google_play=self.contact_google_play
        )

        if l10n_strings is not None:
            create_or_update_listings(edit_service, l10n_strings)

        for path, metadata in apks_metadata_per_paths.items():
            edit_service.upload_apk(path)

            if l10n_strings is not None:
                _create_or_update_whats_new(edit_service, package_name, metadata['version_code'], l10n_strings)

        all_version_codes = _get_ordered_version_codes(apks_metadata_per_paths)
        edit_service.update_track(self.track, all_version_codes, self.rollout_percentage)
        edit_service.commit_transaction()

    def run(self):
        apks_paths = [apk.name for apk in self.apks]
        apks_metadata_per_paths = {
            apk_path: extractor.extract_metadata(apk_path)
            for apk_path in apks_paths
        }
        checker.cross_check_apks(apks_metadata_per_paths,
                                 self.config.skip_checks_fennec,
                                 self.config.skip_check_multiple_locales,
                                 self.config.skip_check_same_locales,
                                 self.config.skip_check_ordered_version_codes,
                                 self.config.skip_check_package_names,
                                 self.config.expected_package_names)

        # Each distinct product must be uploaded in different Google Play transaction, so we split them by package name here.
        split_apk_metadata = _split_apk_metadata_per_package_name(apks_metadata_per_paths)

        for (package_name, apks_metadata) in split_apk_metadata.items():
            if self.google_play_strings_file:
                l10n_strings = json.load(self.google_play_strings_file)
                store_l10n.check_translations_schema(l10n_strings)
                logger.info('Loaded listings and what\'s new section from "{}"'.format(self.google_play_strings_file.name))
            elif self.update_google_play_strings_from_store:
                logger.info("Downloading listings and what's new section from L10n Store...")
                l10n_strings = store_l10n.get_translations_per_google_play_locale_code(package_name)
            elif not self.update_google_play_strings:
                logger.warning("Listing and what's new section won't be updated.")
                l10n_strings = None
            else:
                raise WrongArgumentGiven("Option missing. You must provide what to do in regards to Google Play strings.")

            self.upload_apks(apks_metadata, package_name, l10n_strings)


def _split_apk_metadata_per_package_name(apks_metadata_per_paths):
    split_apk_metadata = {}
    for (apk_path, metadata) in apks_metadata_per_paths.items():
        package_name = metadata['package_name']
        if package_name not in split_apk_metadata:
            split_apk_metadata[package_name] = {}
        split_apk_metadata[package_name].update({apk_path: metadata})

    return split_apk_metadata


def _create_or_update_whats_new(edit_service, package_name, apk_version_code, l10n_strings):
    if package_name == 'org.mozilla.fennec_aurora':
        # See https://github.com/mozilla-l10n/stores_l10n/issues/142
        logger.warning("Nightly detected, What's new section won't be updated")
        return

    for google_play_locale_code, translation in l10n_strings.items():
        try:
            whats_new = translation['whatsnew']
            edit_service.update_whats_new(
                google_play_locale_code, apk_version_code, whats_new=whats_new
            )
        except KeyError:
            logger.warning("No What's new section defined for locale {}".format(google_play_locale_code))


def _get_ordered_version_codes(apks):
    return sorted([apk['version_code'] for apk in apks.values()])


def main(name=None):
    if name not in ('__main__', None):
        return

    from mozapkpublisher.common import main_logging
    main_logging.init()

    parser = ArgumentParser(description='Upload APKs of Firefox for Android on Google play.')

    googleplay.add_general_google_play_arguments(parser)

    parser.add_argument('--track', action='store', required=True,
                        help='Track on which to upload')
    parser.add_argument('--rollout-percentage', type=int, choices=range(0, 101), metavar='[0-100]',
                        default=None,
                        help='The percentage of user who will get the update. Specify only if track is rollout')
    parser.add_argument('--skip-check-ordered-version-codes', action='store_true',
                            help='skip check that asserts version codes are different, x86 code > arm code')
    parser.add_argument('--skip-check-multiple-locales', action='store_true',
                            help='skip check that asserts that apks all have multiple locales')
    parser.add_argument('--skip-check-same-locales', action='store_true',
                            help='skip check that asserts that all apks have the same locales')
    parser.add_argument('--skip-checks-fennec', action='store_true',
                            help='skip checks that are Fennec-specific (ini-checking, checking '
                                 'version-to-package-name compliance')

    parser.add_argument('apks', metavar='path_to_apk', type=argparse.FileType(), nargs='+',
                        help='The path to the APK to upload. You have to provide every APKs for each architecture/API level. \
                                            Missing or extra APKs exit the program without uploading anything')

    expected_package_names_group = parser.add_mutually_exclusive_group(required=True)
    expected_package_names_group.add_argument('--expected-package-name', dest='expected_package_names',
                                              action='append',
                                              help='Package names apks are expected to match')
    expected_package_names_group.add_argument('--skip-check-package-names', action='store_true',
                                              help='Skip assertion that apks match a specified package name')

    google_play_strings_group = parser.add_mutually_exclusive_group(required=True)
    google_play_strings_group.add_argument('--no-gp-string-update', dest='update_google_play_strings',
                                           action='store_false',
                                           help="Don't update listings and what's new sections on Google Play")
    google_play_strings_group.add_argument('--update-gp-strings-from-l10n-store',
                                           dest='update_google_play_strings_from_store',
                                           action='store_true',
                                           help="Download listings and what's new sections from the l10n store and use them \
                                                           to update Google Play")
    google_play_strings_group.add_argument('--update-gp-strings-from-file', dest='google_play_strings_file',
                                           type=argparse.FileType(),
                                           help="Use file to update listing and what's new section on Google Play.\
                                                           Such file can be obtained by calling fetch_l10n_strings.py")

    try:
        config = parser.parse_args()
        push_apk(config.apks, config.service_account, config.google_play_credentials_file, config.track,
                 config.update_google_play_strings, config.update_google_play_strings_from_store,
                 config.google_play_strings_file, config.rollout_percentage, config.commit, config.contact_google_play)
    except WrongArgumentGiven as e:
        parser.print_help(sys.stderr)
        sys.stderr.write('{}: error: {}\n'.format(parser.prog, e))
        raise SystemExit(2)


main(__name__)
