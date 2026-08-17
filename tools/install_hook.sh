#!/bin/bash
HOOK_DIR=".git/hooks"
HOOK_FILE="$HOOK_DIR/pre-commit"

if [ ! -d "$HOOK_DIR" ]; then
    echo "Error: Not a git repository."
    exit 1
fi

echo "#!/bin/bash" > $HOOK_FILE
echo "python cli.py check_diff" >> $HOOK_FILE
chmod +x $HOOK_FILE

echo "Council pre-commit hook installed successfully!"
