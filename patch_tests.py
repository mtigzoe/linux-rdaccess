import re

with open('tests/shared/test_remote_access.py', 'r') as f:
    code = f.read()

# In test_unmapped_nvda_commands_do_not_fall_through_to_orca_bookmarks_or_silence
# Add F5, F12, F3, etc. to the loop.
# Find: (0x55, False),                 # NVDA+U progress reporting vs Orca laptop review line
# Repl: (0x55, False),                 # NVDA+U progress reporting vs Orca laptop review line
#       (0x7B, False),                 # NVDA+F12 vs Orca toggle caret navigation
#       (0x74, False),                 # NVDA+F5 vs Orca something
#       (0x72, False), (0x72, True),   # NVDA+F3 / NVDA+Shift+F3 vs Orca something

target = '(0x55, False),                 # NVDA+U progress reporting vs Orca laptop review line'
repl = target + '''
            (0x7B, False),                 # NVDA+F12
            (0x74, False),                 # NVDA+F5
            (0x72, False), (0x72, True),   # NVDA+F3
            (0x46, False),                 # NVDA+F
'''
code = code.replace(target, repl)

# For NVDA+Ctrl+F we also need to add it to a test or the same test (wait, the test has a `shift` param but not `ctrl` param).
# Let's write a new test or just remove the existing NVDA+Ctrl+F test and verify it does not trigger Orca Find.
code = re.sub(r'def test_remote_nvda_ctrl_f_opens_orca_find_in_document_browse_or_focus_mode\(self\):.*?def test_remote_nvda_ctrl_f_in_browser_chrome_does_not_open_app_find\(self\):', 'def test_remote_nvda_ctrl_f_in_browser_chrome_does_not_open_app_find(self):', code, flags=re.DOTALL)

with open('tests/shared/test_remote_access.py', 'w') as f:
    f.write(code)

print("Patched test.")
