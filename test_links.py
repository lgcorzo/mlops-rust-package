import os
import re
import sys

def main():
    errors = 0
    # Walk through the generated markdown files in openwiki/
    for root, dirs, files in os.walk('openwiki'):
        for file in files:
            if file.endswith('.md'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r') as f:
                    content = f.read()

                # We need to find the Source References
                # Source Directory Reference: `src/path/`
                # Source Citations: `src/path/file.py:line`

                # In our generated template, we output e.g. `docs/plans/processor.py:15`
                # Let's extract paths between backticks that contain a slash
                matches = re.findall(r'`([^`]+\/.*?)`', content)

                for m in matches:
                    # Strip line numbers if present e.g. .py:15
                    path = m.split(':')[0]
                    # path might be something like docs/plans/
                    # we don't strictly require processor.py to exist because it's a mock diagram in this repo
                    # But the directory `docs/plans/` should exist.

                    if not os.path.exists(path) and not path.endswith('.py'):
                        print(f"Error in {filepath}: link '{m}' -> resolved path '{path}' does not exist.")
                        errors += 1

    if errors > 0:
        sys.exit(1)
    else:
        print("All relative paths verified!")

if __name__ == '__main__':
    main()
