# Phase 0: Locate ai_coding_rules Repository

Detect the ai_coding_rules repository location before making any changes.

## Purpose

The rule-learner skill needs to modify files in the ai_coding_rules repository, which may be in a different location than the current working directory. This phase ensures we're making changes in the correct repository.

## When This Runs

**BEFORE all other phases** - This is Phase 0, executed first regardless of where the skill is invoked from.

## Steps

### 1. Check Environment Variable

First, check for `AI_CODING_RULES_REPO` environment variable.

```bash
# Check if environment variable is set
if [ -n "$AI_CODING_RULES_REPO" ]; then
    REPO_PATH="$AI_CODING_RULES_REPO"
    echo "✓ Found environment variable: AI_CODING_RULES_REPO"
    echo "✓ Repository path: $REPO_PATH"
fi
```

**Setup (add to shell profile):**
```bash
# In ~/.zshrc (macOS/most Linux) or ~/.bashrc (Linux)
export AI_CODING_RULES_REPO="/path/to/your/ai_coding_rules"
```

### 2. Check Current Directory

If no environment variable, check if we're already in the ai_coding_rules repository.

```bash
# Check if current directory is ai_coding_rules
if [ -z "$REPO_PATH" ] && [ -d "./rules" ] && [ -f "./AGENTS.md" ] && [ -d "./scripts" ]; then
    # Verify it's the right repo by checking for key files
    if [ -f "./rules/000-global-core.md" ]; then
        REPO_PATH="$(pwd)"
        echo "✓ Current directory is ai_coding_rules repository"
    fi
fi
```

### 3. Search Common Locations

If not in the repo, search common locations.

```bash
if [ -z "$REPO_PATH" ]; then
    SEARCH_PATHS=(
        "$HOME/Programming/ai_coding_rules"
        "$HOME/projects/ai_coding_rules"
        "$HOME/repos/ai_coding_rules"
        "$HOME/ai_coding_rules"
        "$HOME/code/ai_coding_rules"
    )
    
    for path in "${SEARCH_PATHS[@]}"; do
        if [ -d "$path/rules" ] && [ -f "$path/AGENTS.md" ]; then
            REPO_PATH="$path"
            echo "✓ Found repository at: $REPO_PATH"
            break
        fi
    done
fi
```

**Default paths checked (in order):**
1. `~/Programming/ai_coding_rules`
2. `~/projects/ai_coding_rules`
3. `~/repos/ai_coding_rules`
4. `~/ai_coding_rules`
5. `~/code/ai_coding_rules`

### 4. Prompt User If Not Found

If neither current directory nor common locations work, ask user.

```markdown
Repository Detection Failed
================================================================================

Cannot find ai_coding_rules repository.

Please provide the absolute path to your ai_coding_rules repository:

Examples:
  /Users/username/Programming/ai_coding_rules
  /Users/username/repos/ai-coding-rules
  ~/Documents/ai_coding_rules

Path: _
```

**After user provides path:**
```bash
# Use the provided path for this session
REPO_PATH="$USER_PROVIDED_PATH"
echo "✓ Using provided path: $REPO_PATH"
echo ""
echo "To avoid this prompt in future sessions, add to your shell profile:"
echo "  export AI_CODING_RULES_REPO=\"$REPO_PATH\""
echo ""
echo "Add this line to:"
echo "  - Zsh (macOS default): ~/.zshrc"
echo "  - Bash: ~/.bashrc"
echo ""
echo "Then run: source ~/.zshrc (or ~/.bashrc)"
```

### 5. Verify Repository Structure

Confirm the directory is actually an ai_coding_rules repository.

```bash
# Check required directories and files
if [ ! -d "$REPO_PATH/rules" ]; then
    ERROR="rules/ directory not found"
fi

if [ ! -f "$REPO_PATH/AGENTS.md" ]; then
    ERROR="AGENTS.md file not found"
fi

if [ ! -f "$REPO_PATH/rules/RULES_INDEX.md" ]; then
    ERROR="rules/RULES_INDEX.md not found"
fi

if [ ! -d "$REPO_PATH/scripts" ]; then
    ERROR="scripts/ directory not found"
fi
```

**Expected structure:**
```
$REPO_PATH/
├── rules/                    ← Required
│   ├── 000-global-core.md
│   ├── 100-*.md
│   ├── RULES_INDEX.md
│   └── ...
├── AGENTS.md                 ← Required
├── scripts/                  ← Required
│   ├── schema_validator.py
│   ├── index_generator.py
│   └── ...
└── skills/                   ← Optional
```

### 5. Handle Verification Failures

If verification fails, provide helpful error message.

```markdown
Repository Verification Failed
================================================================================

Directory: $REPO_PATH

Missing: $ERROR

This doesn't appear to be a valid ai_coding_rules repository.

Options:
A) Provide a different path
B) Clone the repository:
   git clone <repo-url> ~/Programming/ai_coding_rules
C) Initialize repository structure (advanced)

Choice: _
```

### 6. Set Working Context

Once verified, set the repository path for all subsequent operations.

```bash
# Export for use in all phases
export AI_CODING_RULES_REPO="$REPO_PATH"

# Display confirmation
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "Repository Located"
echo "════════════════════════════════════════════════════════════════════════"
echo "Path: $REPO_PATH"
echo "Current directory: $(pwd)"
echo ""
echo "All changes will be made in: $REPO_PATH"
echo "Your current project directory remains unchanged."
echo "════════════════════════════════════════════════════════════════════════"
echo ""
```

## Outputs

**Success:**
```markdown
Repository Detection:
✓ Location: /Users/rgoldin/Programming/ai_coding_rules
✓ Verified: rules/ directory exists
✓ Verified: AGENTS.md exists
✓ Verified: rules/RULES_INDEX.md exists
✓ Verified: scripts/ directory exists
✓ Context set: All operations will use this repository

Current directory: /Users/rgoldin/projects/my-data-pipeline (unchanged)
```

**Saved to Environment:**
```bash
AI_CODING_RULES_REPO=/Users/rgoldin/Programming/ai_coding_rules
```

## Usage in Subsequent Phases

All phases use `$AI_CODING_RULES_REPO` instead of current directory:

**Phase 1 (Analyze):**
- Runs in current directory (analyzes current project's conversation)
- No repo path needed yet

**Phase 2 (Search):**
```bash
# Search rules in detected repo
grep -i "keyword" $AI_CODING_RULES_REPO/rules/*.md
cat $AI_CODING_RULES_REPO/rules/RULES_INDEX.md
```

**Phase 3 (Enhance/Create):**
```bash
# Modify files in detected repo
vim $AI_CODING_RULES_REPO/rules/207-python-postgres.md
```

**Phase 4 (Validate):**
```bash
# Run validation in repo context
cd $AI_CODING_RULES_REPO
uv run python scripts/schema_validator.py rules/207-python-postgres.md
```

**Phase 5 (Finalize):**
```bash
# Regenerate index in repo
cd $AI_CODING_RULES_REPO
uv run python scripts/index_generator.py
```

**Phase 6 (Commit):**
```bash
# Commit in repo (not current project)
cd $AI_CODING_RULES_REPO
git add rules/207-python-postgres.md rules/RULES_INDEX.md
git commit -m "..."
```

## Error Handling

### Path Doesn't Exist

```
If provided path doesn't exist:
  ERROR: "Directory not found: $REPO_PATH"
  ASK: "Did you mean to:
    A) Create this directory
    B) Provide a different path
    C) Clone repository to this location"
```

### Multiple Repositories Found

```
If multiple possible repositories detected:
  SHOW: List of found repositories
  ASK: "Multiple repositories found. Which one?
    1) /Users/rgoldin/Programming/ai_coding_rules
    2) /Users/rgoldin/repos/ai-coding-rules
    3) Other (specify path)"
```

## Cross-Project Workflow Example

**Scenario:** Working in project A, learning applies to ai_coding_rules

```bash
# You're in your data pipeline project
$ cd ~/projects/snowflake-data-pipeline
$ pwd
/Users/rgoldin/projects/snowflake-data-pipeline

# Use rule-learner skill
$ Use rule-learner skill
conversation_summary: "Dynamic Tables need REFRESH_MODE..."
```

**Phase 0 execution:**
```
Phase 0: Locate Repository
✓ Checking current directory... not ai_coding_rules
✓ Searching common locations...
✓ Found: /Users/rgoldin/Programming/ai_coding_rules
✓ Verified: rules/ exists
✓ Verified: AGENTS.md exists
✓ Context set

Current directory: /Users/rgoldin/projects/snowflake-data-pipeline
Repository: /Users/rgoldin/Programming/ai_coding_rules

All changes will be made in repository, not current directory.
```

**After completion:**
```
✓ Changes made in: /Users/rgoldin/Programming/ai_coding_rules
✓ Current directory: /Users/rgoldin/projects/snowflake-data-pipeline (unchanged)
✓ Rule updated: rules/112-snowflake-dynamic-tables.md
✓ Committed: abc1234
```

## Benefits

1. **Works from any directory** - Use the skill regardless of current location
2. **Protects current project** - Never modifies current project's files
3. **Centralized rules** - All rule updates go to one canonical repository
4. **No manual navigation** - No need to cd to ai_coding_rules first
5. **Simple detection** - Searches common paths automatically

## Next Phase

**Proceed to:** `workflows/01-analyze.md`

**Carry forward:**
- `$AI_CODING_RULES_REPO` - Repository path for all file operations
- Current directory - Preserved for conversation context
