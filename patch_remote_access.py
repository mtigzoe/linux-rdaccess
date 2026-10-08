import re

with open('linux_rdaccess_core/connection/remote_access.py', 'r') as f:
    code = f.read()

# 1. Remove F (find)
code = re.sub(r'if vk_code == 0x46 and ctrl and not shifts and not alt_win:\s+browse_action = "find"\s+elif ', 'if ', code)

# 2. Remove F3 (findNext/Previous)
code = re.sub(r'elif vk_code == 0x72 and not ctrl and not alt_win:\s+browse_action = "findPrevious" if shifts else "findNext"\s+', '', code)

# 3. Add to collision list for F12, F5, F3
# Find: or (vk_code in (0x46, 0x4B, 0x53) and not shifts and not other)
# Replace with: or (vk_code in (0x46, 0x4B, 0x53) and not shifts and not other) or (vk_code in (0x72, 0x74, 0x7B) and not other)
code = re.sub(r'or \(vk_code in \(0x46, 0x4B, 0x53\)\n\s+and not shifts and not other\)',
              'or (vk_code in (0x46, 0x4B, 0x53)\n                    and not shifts and not other)\n                or (vk_code in (0x72, 0x74, 0x7B) and not other)', code)

# 4. Add Ctrl+F to the collision list
# Find: 0x42, 0x44, 0x57, 0x43, 0x52, 0x5A, 0x54, 0x50)
# Replace with: 0x42, 0x44, 0x57, 0x43, 0x52, 0x5A, 0x54, 0x50, 0x46)
code = re.sub(r'0x42, 0x44, 0x57, 0x43, 0x52, 0x5A, 0x54, 0x50\)', '0x42, 0x44, 0x57, 0x43, 0x52, 0x5A, 0x54, 0x50, 0x46)', code)

# 5. Remove _lrd_consume_find, etc? The hook is safe to keep or we can remove it. Let's keep it to avoid touching too much Orca-side code if not necessary. But actually wait, if we never send find, we can remove it. Let's leave it for now.

with open('linux_rdaccess_core/connection/remote_access.py', 'w') as f:
    f.write(code)

print("Patched.")
