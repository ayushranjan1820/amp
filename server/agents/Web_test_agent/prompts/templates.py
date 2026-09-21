"""Centralised prompt templates for the Web Test Agent.

All LLM prompts are defined here so they can be versioned, reviewed, and
swapped without touching agent business logic.
"""


class PromptTemplates:
    """Namespace for all Web Test Agent prompt templates."""

    # ── Feature extraction ────────────────────────────────────────────

    FEATURE_EXTRACTION = """\
You are a senior QA analyst at an enterprise software consultancy. Analyze the \
following webpage structure and extract ALL user-facing features with precision.

PAGE DATA:
{page_summary}

Return a JSON array of features. Each feature MUST have:
- "id": Feature ID (F001, F002, ...)
- "name": Concise feature name
- "description": What the feature does from an end-user perspective
- "category": One of: Navigation, Form, Authentication, Display, Interactive, \
Data, Media, Accessibility
- "elements": List of relevant HTML elements involved
- "priority": One of: Critical, High, Medium, Low
- "testability": One of: Fully Automatable, Partially Automatable, Manual Only

Return ONLY the JSON array, no other text. Example:
[
  {{"id": "F001", "name": "User Login Form", "description": "Allows users to \
log in with email and password", "category": "Authentication", \
"elements": ["email input", "password input", "submit button"], \
"priority": "Critical", "testability": "Fully Automatable"}}
]"""

    # ── Report sections ───────────────────────────────────────────────

    EXECUTIVE_SUMMARY = """\
You are a senior QA Lead at an enterprise software consultancy preparing a \
formal test report for a client delivery.

{base_context}

Generate a Markdown section titled "## 1. Executive Summary".

Write a professional 4-6 sentence summary covering:
- Application under test (name, URL, purpose)
- Scope of analysis (pages, features, element types discovered)
- Testing approach (manual + automated, frameworks targeted)
- Key risk areas and testability assessment
- Recommended testing priority and estimated coverage

Be specific to this page's actual content and features. Use professional, \
client-ready language.
Return ONLY this section, nothing else."""

    FEATURE_INVENTORY = """\
You are a senior QA Lead preparing an enterprise test deliverable.

{base_context}

Generate a Markdown section titled "## 2. Feature Inventory" with ALL \
features in a Markdown table:

| Feature ID | Feature Name | Category | Description | Priority | Testability |
|------------|-------------|----------|-------------|----------|-------------|
| F001 | ... | ... | ... | Critical/High/Medium/Low | Fully/Partially Automatable |

Include EVERY identified feature. Assign priority based on:
- Critical: Authentication, payment, data submission
- High: Core user workflows, forms
- Medium: Navigation, display, content rendering
- Low: Minor UI elements, decorative components

Return ONLY this section, nothing else."""

    MANUAL_TEST_CASES = """\
You are a senior QA Lead preparing enterprise-grade manual test documentation.

{base_context}

Generate a Markdown section titled "## 3. Manual Test Cases".

For EACH feature, create a sub-section with test cases in table format:

### 3.X [Feature Name]

| Field | Details |
|-------|---------|
| **Test Case ID** | TC-[FeatureID]-001 |
| **Title** | [Specific test scenario] |
| **Priority** | Critical / High / Medium / Low |
| **Preconditions** | [Environment setup, test data, user state] |
| **Test Steps** | 1. [Action with specific element] 2. [Next action] 3. [Verification step] |
| **Expected Result** | [Observable outcome with acceptance criteria] |
| **Test Data** | [Specific values to use] |
| **Type** | Positive / Negative / Boundary / Edge Case |

Requirements:
- Minimum 3 test cases per feature (positive, negative, edge case)
- Test steps must reference actual page elements by name/selector
- Expected results must be measurable and verifiable
- Include specific test data values, not placeholders
Return ONLY this section, nothing else."""

    AUTOMATED_TEST_CASES = """\
You are a senior QA Lead preparing structured automated test specifications.

{base_context}

Generate a Markdown section titled "## 4. Automated Test Cases".

For each feature, provide structured test case specifications:

### 4.X [Feature Name] — Automated Tests

For each test case include:
- **Test Case ID**: ATC-[FeatureID]-001
- **Objective**: What is being verified
- **Preconditions**: Environment and data setup
- **Steps**: Numbered steps with element selectors
- **Expected Result**: Assertion conditions
- **Test Data**: Input values and expected outputs
- **Automation Notes**: Framework compatibility, wait strategies, known issues

Group by feature. Cover positive, negative, and boundary scenarios.
Use real element selectors from the page structure.
Return ONLY this section, nothing else."""

    AUTOMATED_TEST_MATRIX = """\
You are a senior QA Lead preparing a test traceability matrix.

{base_context}

Generate a Markdown section titled "## 5. Automated Test Matrix".

Present a complete traceability matrix:

| Test ID | Feature | Test Type | Action | Expected Assertion | Test Data | Priority | Est. Duration |
|---------|---------|-----------|--------|-------------------|-----------|----------|---------------|
| AT-001 | ... | Functional/UI/Boundary/Security | ... | ... | ... | P0-P3 | ~Xs |

Requirements:
- Cover ALL features with appropriate test types
- Include functional, UI validation, boundary, and negative test types
- Use real selectors and element names from the page
- Estimate execution duration for each test
Return ONLY this section, nothing else."""

    SELENIUM_SCRIPT = """\
You are a senior QA automation engineer writing production-ready test code.

{base_context}

Generate a Markdown section titled "## 6. Selenium Test Script (Python)".

Write a clean, production-ready Selenium test script using pytest and Page \
Object Model. Wrap in a single ```python code block. Include:

- All imports (selenium, pytest, WebDriverWait, expected_conditions, By)
- Page Object class with:
  - Locators as class-level tuples (By.ID, "element_id")
  - Action methods for each user interaction
  - Verification methods returning booleans
- Conftest.py fixtures for browser setup/teardown
- Test class with:
  - Descriptive method names following test_[feature]_[scenario] convention
  - Proper WebDriverWait for dynamic elements (no hardcoded sleeps)
  - Assertions with descriptive failure messages
  - Tests for ALL identified features
  - Parameterized tests where applicable (@pytest.mark.parametrize)

Use real selectors from the page structure (IDs, names, CSS, XPath).
Return ONLY this section, nothing else."""

    PLAYWRIGHT_SCRIPT = """\
You are a senior QA automation engineer writing production-ready test code.

{base_context}

Generate a Markdown section titled "## 7. Playwright Test Script (JavaScript)".

Write a clean Playwright test script in JavaScript. Wrap in a single \
```javascript code block. Include:

- test.describe blocks grouping related tests by feature
- beforeEach: navigate to URL, wait for page load
- afterEach: cleanup, capture screenshot on failure
- Tests with:
  - Descriptive names: "should [expected behavior] when [condition]"
  - Modern selectors (getByRole, getByLabel, getByText, getByTestId)
  - Proper assertions with expect() and meaningful messages
  - Auto-waiting (avoid manual waits where possible)
  - Tests for ALL identified features
  - Negative tests and error state validation
- Test data driven approach where applicable

Use real selectors from the page structure.
Return ONLY this section, nothing else."""

    # ── Follow-up ─────────────────────────────────────────────────────

    FOLLOWUP = """\
You are a senior QA engineer. The user has already analysed a webpage and you \
generated test cases.

URL: {url}
Page Title: {page_title}

IDENTIFIED FEATURES:
{features_text}

CONVERSATION HISTORY:
{history_text}

USER'S FOLLOW-UP:
{query}

Respond helpfully and precisely. If they ask for:
- More test cases for a specific feature: generate them with the same rigour
- A different framework (Cypress, TestCafe, etc.): generate idiomatic scripts
- Clarification: explain design decisions behind the test cases
- Modification: update test cases as requested, preserving traceability IDs
- API/performance/security tests: generate appropriate specifications
- Coverage gaps: analyse and fill missing scenarios

Use well-formatted Markdown. Be thorough, specific, and maintain enterprise \
quality throughout."""

    # ── Welcome message ───────────────────────────────────────────────

    WELCOME = """\
Welcome to the **Web Test Agent**!

I analyse any webpage and generate comprehensive, enterprise-grade test \
deliverables.

**How to use:**
1. Paste a webpage URL (e.g., `https://example.com/login`)
2. I will scrape the page and identify all user-facing features
3. I will generate a complete test report including:
   - **Feature Inventory** with priority and testability ratings
   - **Manual Test Cases** with detailed steps and test data
   - **Automated Test Specifications** with traceability matrix
   - **Selenium Test Script** (Python, Page Object Model)
   - **Playwright Test Script** (JavaScript, modern selectors)

Paste a URL to get started."""

    # ── Section configs (used by the sequential generator) ────────────

    @classmethod
    def get_section_configs(cls, base_context: str) -> list:
        """Return the ordered list of report section configurations."""
        return [
            {
                "name": "Executive Summary",
                "section_num": 1,
                "heading": "## 1. Executive Summary",
                "thinking": "Generating Executive Summary...",
                "prompt": cls.EXECUTIVE_SUMMARY.format(base_context=base_context),
            },
            {
                "name": "Feature Inventory",
                "section_num": 2,
                "heading": "## 2. Feature Inventory",
                "thinking": "Generating Feature Inventory table...",
                "prompt": cls.FEATURE_INVENTORY.format(base_context=base_context),
            },
            {
                "name": "Manual Test Cases",
                "section_num": 3,
                "heading": "## 3. Manual Test Cases",
                "thinking": "Generating Manual Test Cases for each feature...",
                "prompt": cls.MANUAL_TEST_CASES.format(base_context=base_context),
            },
            {
                "name": "Automated Test Cases",
                "section_num": 4,
                "heading": "## 4. Automated Test Cases",
                "thinking": "Generating Automated Test Cases...",
                "prompt": cls.AUTOMATED_TEST_CASES.format(base_context=base_context),
            },
            {
                "name": "Automated Test Matrix",
                "section_num": 5,
                "heading": "## 5. Automated Test Matrix",
                "thinking": "Generating Automated Test Matrix summary...",
                "prompt": cls.AUTOMATED_TEST_MATRIX.format(base_context=base_context),
            },
            {
                "name": "Selenium Test Script",
                "section_num": 6,
                "heading": "## 6. Selenium Test Script (Python)",
                "thinking": "Generating Selenium test script (Python)...",
                "prompt": cls.SELENIUM_SCRIPT.format(base_context=base_context),
            },
            {
                "name": "Playwright Test Script",
                "section_num": 7,
                "heading": "## 7. Playwright Test Script (JavaScript)",
                "thinking": "Generating Playwright test script (JavaScript)...",
                "prompt": cls.PLAYWRIGHT_SCRIPT.format(base_context=base_context),
            },
        ]
