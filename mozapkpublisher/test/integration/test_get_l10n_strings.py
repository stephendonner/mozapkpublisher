import json
import os
import pytest
import tempfile

from distutils.util import strtobool

from mozapkpublisher.get_l10n_strings import get_l10n_strings
from mozapkpublisher.common.store_l10n import STORE_PRODUCT_DETAILS_PER_PACKAGE_NAME, check_translations_schema


@pytest.mark.skipif(strtobool(os.environ.get('SKIP_NETWORK_TESTS', 'true')), reason='Tests requiring network are skipped')
@pytest.mark.parametrize('package_name', STORE_PRODUCT_DETAILS_PER_PACKAGE_NAME.keys())
def test_download_files(package_name):
    with tempfile.NamedTemporaryFile('w+t', encoding='utf-8') as f:
        get_l10n_strings(package_name, f)

        f.seek(0)
        data = json.load(f)
        # In reality, this call is already done by GetL10nStrings, but better safe than sorry
        check_translations_schema(data)
