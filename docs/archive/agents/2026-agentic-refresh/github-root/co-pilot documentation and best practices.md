Agent Best Practices:

Making sure your issues are well-scoped
GitHub Copilot provides better results when assigned clear, well-scoped tasks. An ideal task includes:

A clear description of the problem to be solved or the work required.
Complete acceptance criteria on what a good solution looks like (for example, should there be unit tests?).
Directions about which files need to be changed.
If you pass a task to Copilot by assigning an issue, it's useful to think of the issue you assign to Copilot as a prompt. Consider whether the issue description is likely to work as an AI prompt, and will enable Copilot to make the required code changes.

Choosing the right type of tasks to give to Copilot
As you work with Copilot, you'll get a sense of the types of tasks it's best suited to work on. Initially, you might want to start by giving Copilot simpler tasks, to see how it works as a coding agent. For example, you could start by asking Copilot to fix bugs, alter user interface features, improve test coverage, update documentation, improve accessibility, or address technical debt.

Issues that you may choose to work on yourself, rather than assigning to Copilot, include:

Complex and broadly scoped tasks

Broad-scoped, context-rich refactoring problems requiring cross-repository knowledge and testing
Complex issues requiring understanding dependencies and legacy code
Tasks that require deep domain knowledge
Tasks that involve substantial business logic
Large changes to a codebase requiring design consistency
Sensitive and critical tasks

Production-critical issues
Tasks involving security, personally identifiable information, authentication repercussions
Incident response
Ambiguous tasks

Tasks lacking clear definition: tasks with ambiguous requirements, open-ended tasks, tasks that require working through uncertainty to find a solution
Learning tasks

Tasks where the developer wants to learn to achieve a deeper understanding
Using comments to iterate on a pull request
Working with Copilot on a pull request is just like working with a human developer: it's common for the pull request to need further work before it can be merged. The process for getting the pull request to a mergeable state is exactly the same when the pull request is created by Copilot as when it's created by a human.

You can also mention @copilot in comments on the pull request—explaining what you think is incorrect, or could be improved—and leave Copilot to make the required changes. Alternatively, you can work on the feature branch yourself and push changes to the pull request.

After a user with write access mentions @copilot in a comment, Copilot will start to make any required changes, and will update the pull request when it's done. Because Copilot starts looking at comments as soon as they are submitted, if you are likely to make multiple comments on a pull request it's best to batch them by clicking Start a review, rather than clicking Add single comment. You can then submit all of your comments at once, triggering Copilot to work on your entire review, rather than working on individual comments separately.

Note

Copilot only responds to comments from people who have write access to the repository.

As Copilot makes changes to the pull request, it will keep the title and body up to date so they reflect the current changes.

Adding custom instructions to your repository
By adding custom instructions to your repository, you can guide Copilot on how to understand your project and how to build, test and validate its changes.

If Copilot is able to build, test and validate its changes in its own development environment, it is more likely to produce good pull requests which can be merged quickly.

Copilot coding agent supports a number of different types of custom instructions files:

/.github/copilot-instructions.md
/.github/instructions/**/*.instructions.md
**/AGENTS.md
/CLAUDE.md
/GEMINI.md
For more information, see Adding repository custom instructions for GitHub Copilot.

Repository-wide instructions
To add instructions that apply to all tasks assigned to Copilot in your repository, create a .github/copilot-instructions.md file in the root of your repository. This file should contain information about your project, such as how to build and test it, and any coding standards or conventions you want Copilot to follow. Note that the instructions will also apply to Copilot Chat and Copilot code review.

The first time you ask Copilot to create a pull request in a given repository, Copilot will leave a comment with a link to automatically generate custom instructions. You can also ask Copilot to generate custom instructions for you at any time using our recommended prompt. See Adding repository custom instructions for GitHub Copilot.

You can also choose to write your own custom instructions at any time. Here is an example of an effective copilot-instructions.md file:

This is a Go based repository with a Ruby client for certain API endpoints. It is primarily responsible for ingesting metered usage for GitHub and recording that usage. Please follow these guidelines when contributing:

## Code Standards

### Required Before Each Commit
- Run `make fmt` before committing any changes to ensure proper code formatting
- This will run gofmt on all Go files to maintain consistent style

### Development Flow
- Build: `make build`
- Test: `make test`
- Full CI check: `make ci` (includes build, fmt, lint, test)

## Repository Structure
- `cmd/`: Main service entry points and executables
- `internal/`: Logic related to interactions with other GitHub services
- `lib/`: Core Go packages for billing logic
- `admin/`: Admin interface components
- `config/`: Configuration files and templates
- `docs/`: Documentation
- `proto/`: Protocol buffer definitions. Run `make proto` after making updates here.
- `ruby/`: Ruby implementation components. Updates to this folder should include incrementing this version file using semantic versioning: `ruby/lib/billing-platform/version.rb`
- `testing/`: Test helpers and fixtures

## Key Guidelines
1. Follow Go best practices and idiomatic patterns
2. Maintain existing code structure and organization
3. Use dependency injection patterns where appropriate
4. Write unit tests for new functionality. Use table-driven unit tests when possible.
5. Document public APIs and complex logic. Suggest changes to the `docs/` folder when appropriate
Path-specific instructions
To add instructions that apply to specific types of files Copilot will work on, like unit tests or React components, create one or more .github/instructions/**/*.instructions.md files in your repository. In these files, include information about the file types, such as how to build and test them, and any coding standards or conventions you want Copilot to follow.

Using the glob pattern in the front matter of the instructions file, you can specify the file types to which they should apply. For example, to create instructions for Playwright tests you could create an instructions file called .github/instructions/playwright-tests.instructions.md with the following content:

---
applyTo: "**/tests/*.spec.ts"
---

## Playwright test requirements

When writing Playwright tests, please follow these guidelines to ensure consistency and maintainability:

1. **Use stable locators** - Prefer `getByRole()`, `getByText()`, and `getByTestId()` over CSS selectors or XPath
1. **Write isolated tests** - Each test should be independent and not rely on other tests' state
1. **Follow naming conventions** - Use descriptive test names and `*.spec.ts` file naming
1. **Implement proper assertions** - Use Playwright's `expect()` with specific matchers like `toHaveText()`, `toBeVisible()`
1. **Leverage auto-wait** - Avoid manual `setTimeout()` and rely on Playwright's built-in waiting mechanisms
1. **Configure cross-browser testing** - Test across Chromium, Firefox, and WebKit browsers
1. **Use Page Object Model** - Organize selectors and actions into reusable page classes for maintainability
1. **Handle dynamic content** - Properly wait for elements to load and handle loading states
1. **Set up proper test data** - Use beforeEach/afterEach hooks for test setup and cleanup
1. **Configure CI/CD integration** - Set up headless mode, screenshots on failure, and parallel execution
Using the Model Context Protocol (MCP)
You can extend the capabilities of Copilot coding agent by using MCP. This allows Copilot coding agent to use tools provided by local and remote MCP servers. The GitHub MCP server and Playwright MCP server are enabled by default. For more information, see Extending GitHub Copilot coding agent with the Model Context Protocol (MCP).

Creating custom agents
While custom instructions help guide Copilot's general behavior across your repository, custom agents create entirely specialized agents with focused expertise and tailored tool configurations. These agents are designed for specific, recurring workflows where domain expertise and consistent behavior are crucial. Custom agents are defined as Markdown files called agent profiles.

Here are some examples of custom agents you could create:

Testing specialist: An agent configured with specific testing frameworks and focused on test coverage, test quality, and testing best practices. It might be limited to read, search, and edit tools to prevent unintended changes to production code while ensuring comprehensive test coverage.
Documentation expert: An agent specialized in creating and maintaining project documentation, with deep knowledge of documentation standards, style guides, and the ability to analyze code to generate accurate API documentation and user guides.
Python specialist: A language-specific agent that understands Python conventions, popular frameworks like Django or Flask, and follows PEP standards. It would have specialized knowledge of Python tooling, virtual environments, and testing frameworks like pytest.
By default, custom agents inherit any MCP server tools that have been configured in the repository, but you can also configure custom agents to only have access to specific tools.

You can use custom agents anywhere you use Copilot coding agent, including when assigning an issue or prompting with a task.

For more information on creating and configuring custom agents, see Creating custom agents.

Pre-installing dependencies in GitHub Copilot's environment
While working on a task, Copilot has access to its own ephemeral development environment, powered by GitHub Actions, where it can explore your code, make changes, execute automated tests and linters and more.

If Copilot is able to build, test and validate its changes in its own development environment, it is more likely to produce good pull requests which can be merged quickly.

To do that, it will need your project's dependencies. Copilot can discover and install these dependencies itself via a process of trial and error - but this can be slow and unreliable, given the non-deterministic nature of large language models (LLMs).

You can configure a copilot-setup-steps.yml file to pre-install these dependencies before the agent starts working so it can hit the ground running. For more information, see Customizing the development environment for GitHub Copilot coding agent.

Preinstalling tools or dependencies in Copilot's environment
In its ephemeral development environment, Copilot can build or compile your project and run automated tests, linters and other tools. To do this, it will need to install your project's dependencies.

Copilot can discover and install these dependencies itself via a process of trial and error, but this can be slow and unreliable, given the non-deterministic nature of large language models (LLMs), and in some cases, it may be completely unable to download these dependencies—for example, if they are private.

Instead, you can preconfigure Copilot's environment before the agent starts by creating a special GitHub Actions workflow file, located at .github/workflows/copilot-setup-steps.yml within your repository.

A copilot-setup-steps.yml file looks like a normal GitHub Actions workflow file, but must contain a single copilot-setup-steps job. This job will be executed in GitHub Actions before Copilot starts working. For more information on GitHub Actions workflow files, see Workflow syntax for GitHub Actions.

Note

The copilot-setup-steps.yml workflow won't trigger unless it's present on your default branch.

Here is a simple example of a copilot-setup-steps.yml file for a TypeScript project that clones the project, installs Node.js and downloads and caches the project's dependencies. You should customize this to fit your own project's language(s) and dependencies:

YAML
name: "Copilot Setup Steps"

# Automatically run the setup steps when they are changed to allow for easy validation, and
# allow manual testing through the repository's "Actions" tab
on:
  workflow_dispatch:
  push:
    paths:
      - .github/workflows/copilot-setup-steps.yml
  pull_request:
    paths:
      - .github/workflows/copilot-setup-steps.yml

jobs:
  # The job MUST be called `copilot-setup-steps` or it will not be picked up by Copilot.
  copilot-setup-steps:
    runs-on: ubuntu-latest

    # Set the permissions to the lowest permissions possible needed for your steps.
    # Copilot will be given its own token for its operations.
    permissions:
      # If you want to clone the repository as part of your setup steps, for example to install dependencies, you'll need the `contents: read` permission. If you don't clone the repository in your setup steps, Copilot will do this for you automatically after the steps complete.
      contents: read

    # You can define any steps you want, and they will run before the agent starts.
    # If you do not check out your code, Copilot will do this for you.
    steps:
      - name: Checkout code
        uses: actions/checkout@v5

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"

      - name: Install JavaScript dependencies
        run: npm ci
In your copilot-setup-steps.yml file, you can only customize the following settings of the copilot-setup-steps job. If you try to customize other settings, your changes will be ignored.

steps (see above)
permissions (see above)
runs-on (see below)
services
snapshot
timeout-minutes (maximum value: 59)
For more information on these options, see Workflow syntax for GitHub Actions.

Any value that is set for the fetch-depth option of the actions/checkout action will be overridden to allow the agent to rollback commits upon request, while mitigating security risks. For more information, see actions/checkout/README.md.

Your copilot-setup-steps.yml file will automatically be run as a normal GitHub Actions workflow when changes are made, so you can see if it runs successfully. This will show alongside other checks in a pull request where you create or modify the file.

Once you have merged the yml file into your default branch, you can manually run the workflow from the repository's Actions tab at any time to check that everything works as expected. For more information, see Manually running a workflow.

When Copilot starts work, your setup steps will be run, and updates will show in the session logs. See Tracking GitHub Copilot's sessions.

If any setup step fails by returning a non-zero exit code, Copilot will skip the remaining setup steps and begin working with the current state of its development environment.

Setting environment variables in Copilot's environment
You may want to set environment variables in Copilot's environment to configure or authenticate tools or dependencies that it has access to.

To set an environment variable for Copilot, create a GitHub Actions variable or secret in the copilot environment. If the value contains sensitive information, for example a password or API key, it's best to use a GitHub Actions secret.

On GitHub, navigate to the main page of the repository.

Under your repository name, click  Settings. If you cannot see the "Settings" tab, select the  dropdown menu, then click Settings.

Screenshot of a repository header showing the tabs. The "Settings" tab is highlighted by a dark orange outline.
In the left sidebar, click Environments.

Click the copilot environment.

To add a secret, under "Environment secrets," click Add environment secret. To add a variable, under "Environment variables," click Add environment variable.

Fill in the "Name" and "Value" fields, and then click Add secret or Add variable as appropriate.

Upgrading to larger GitHub-hosted GitHub Actions runners
By default, Copilot works in a standard GitHub Actions runner with limited resources.

You can choose instead to use larger runners with more advanced features—for example more RAM, CPU and disk space and advanced networking controls. You may want to upgrade to a larger runner if you see poor performance—for example when downloading dependencies or running tests. For more information, see Larger runners.

Before Copilot can use larger runners, you must first add one or more larger runners and then configure your repository to use them. See Managing larger runners. Once you have done this, you can use the copilot-setup-steps.yml file to tell Copilot to use the larger runners.

To use larger runners, set the runs-on step of the copilot-setup-steps job to the label and/or group for the larger runners you want Copilot to use. For more information on specifying larger runners with runs-on, see Running jobs on larger runners.

# ...

jobs:
  copilot-setup-steps:
    runs-on: ubuntu-4-core
    # ...
Note

Copilot coding agent is only compatible with Ubuntu x64 Linux runners. Runners with Windows, macOS or other operating systems are not supported.
Self-hosted GitHub Actions runners are not supported.
Using self-hosted GitHub Actions runners with ARC
You can use self-hosted GitHub Actions runners to support Copilot coding agent using ARC (Actions Runner Controller). This allows you to run Copilot's development environment on your own infrastructure.

Before Copilot can use self-hosted runners, you must first set up ARC-managed scale sets in your environment. For more information, see Actions Runner Controller.

To use self-hosted runners with ARC, update the runs-on attribute in your copilot-setup-steps job to target your ARC-managed scale set:

# ...

jobs:
  copilot-setup-steps:
    runs-on: arc-scale-set-name
    # ...
Replace arc-scale-set-name with the name of your ARC-managed scale set.

Warning

Persistent runners are not recommended for autoscaling scenarios with Copilot coding agent.

Note

ARC is the only officially supported solution for self-hosting Copilot coding agent.
Copilot coding agent is only compatible with Ubuntu x64 Linux runners. Runners with Windows, macOS or other operating systems are not supported.
For more information about ARC, see Actions Runner Controller.
Repository firewall requirements
To enable communication between Copilot coding agent and your self-hosted runners, you must disable the repository firewall in the coding agent's repository settings. Without this change, runners will not be able to connect to Copilot.

For more information about disabling the firewall, see Customizing or disabling the firewall for GitHub Copilot coding agent.

Warning

Disabling the firewall reduces isolation between Copilot and your self-hosted environment. You must implement alternative network security controls to protect your environment.

Security considerations for self-hosted runners
When using self-hosted runners, especially with the firewall disabled, ensure your hosting environment has strict network communication controls. The following endpoints must be reachable from your runners:

api.githubcopilot.com
uploads.github.com
user-images.githubusercontent.com
Enabling Git Large File Storage (LFS)
If you use Git Large File Storage (LFS) to store large files in your repository, you will need to customize Copilot's environment to install Git LFS and fetch LFS objects.

To enable Git LFS, add a actions/checkout step to your copilot-setup-steps job with the lfs option set to true.

YAML
# ...

jobs:
  copilot-setup-steps:
    runs-on: ubuntu-latest
    permissions:
      contents: read # for actions/checkout
    steps:
      - uses: actions/checkout@v5
        with:
          lfs: true
...




Further reading


Allowlisting additional hosts in the agent's firewall
You can allowlist additional addresses in the agent's firewall.

On GitHub, navigate to the main page of the repository.

Under your repository name, click  Settings. If you cannot see the "Settings" tab, select the  dropdown menu, then click Settings.

Screenshot of a repository header showing the tabs. The "Settings" tab is highlighted by a dark orange outline.
In the "Code & automation" section of the sidebar, click Copilot then coding agent.

Click Custom allowlist

Add the addresses you want to include in the allowlist. You can include:

Domains (for example, packages.contoso.corp). Traffic will be allowed to the specified domain and any subdomains.

Example: packages.contoso.corp will allow traffic to packages.contoso.corp and prod.packages.contoso.corp, but not artifacts.contoso.corp.

URLs (for example, https://packages.contoso.corp/project-1/). Traffic will only be allowed on the specified scheme (https) and host (packages.contoso.corp), and limited to the specified path and descendant paths.

Example: https://packages.contoso.corp/project-1/ will allow traffic to https://packages.contoso.corp/project-1/ and https://packages.contoso.corp/project-1/tags/latest, but not https://packages.consoto.corp/project-2, ftp://packages.contoso.corp or https://artifacts.contoso.corp.

Click Add Rule.

After validating your list, click Save changes.
