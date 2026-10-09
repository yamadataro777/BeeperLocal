import unittest
from scripts.macos_compatibility import load_commands, portable_reference, version


class MacCompatibilityTests(unittest.TestCase):
    def test_minimum_os_is_not_a_dylib_version_or_sdk_version(self):
        minimum, libraries, rpaths = load_commands('''file:
Load command 0
          cmd LC_ID_DYLIB
         name @rpath/libssl.dylib (offset 24)
      current version 3.0.0
Load command 1
          cmd LC_BUILD_VERSION
     platform 1
        minos 26.0
          sdk 26.5
Load command 2
          cmd LC_LOAD_DYLIB
         name @loader_path/libcrypto.3.dylib (offset 24)
      current version 3.0.0
Load command 3
          cmd LC_RPATH
         path /opt/homebrew/opt/openssl/lib (offset 12)
''')
        self.assertEqual(minimum, '26.0')
        self.assertGreater(version(minimum), version('13.0'))
        self.assertEqual(libraries, ['@loader_path/libcrypto.3.dylib'])
        self.assertFalse(portable_reference(rpaths[0]))
        self.assertTrue(portable_reference('@loader_path', rpath=True))
        self.assertFalse(portable_reference('@loader_path'))
        self.assertFalse(portable_reference('@loader_path_extra', rpath=True))

    def test_legacy_minimum_and_missing_load_commands(self):
        result = load_commands('''Load command 0
          cmd LC_VERSION_MIN_MACOSX
      version 11.0
          sdk 15.0
''')
        self.assertEqual(result[0], '11.0')
        for text in ('', 'Load command 0\n cmd LC_LOAD_DYLIB\n current version 26.0'):
            with self.assertRaises(ValueError):
                load_commands(text)
        for name in ('/Library/Frameworks/Python.framework/Python', '/Users/fixture/lib.dylib', 'libssl.dylib'):
            self.assertFalse(portable_reference(name))
