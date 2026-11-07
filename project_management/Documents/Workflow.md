# Teamwork Methodology

This document describes the collaboration workflow and development practices followed in this project.

## 1. Branching Strategy

To ensure structured collaboration and avoid conflicts in the main codebase, we follow a branch-based workflow:

- Each team member works on their **own branch**, named after their first name.
  - Example:
    - `juanlu`
    - `grei`
    - `ari`
- The `main` branch is reserved for **stable and reviewed code only**.
- Direct commits to `main` are not allowed.

This approach ensures parallel development while maintaining stability in the production branch.

---

## 2. Merge Request (Pull Request) Policy

All changes must be submitted through a **Merge Request (MR)** to the `main` branch.

Rules:

- A Merge Request must be reviewed by **at least one other team member**.
- The author of the branch cannot approve their own Merge Request.
- Code must compile/run correctly before requesting a merge.
- Reviewers must verify:
  - Code functionality
  - No unintended side effects
  - Clear and readable implementation

---

## 3. Issue Tracking

We use GitLab Issues to organize and track project tasks.

Each issue must:

- Have a clear and descriptive title
- Contain an explanation of the task
- Be assigned to one team member
- Be labeled with one of the predefined categories

### Issue Labels

We use the following four labels to categorize tasks:

- `Documentation`
- `Code Feature`
- `Research`
- `Others`

These labels allow us to monitor workload distribution and maintain transparency regarding each member’s contributions.

---

## 4. Task Assignment

- Every issue is assigned to a responsible team member.
- The assignee is responsible for:
  - Implementing the solution
  - Opening a Merge Request
  - Linking the Issue to the Merge Request
  - Closing the issue.

---

## 5. Commit Guidelines

To maintain clarity in project history:

- Commits must have clear and descriptive messages.
- Avoid generic messages such as:
  - `fix`
  - `update`
  - `changes`
- Preferred format:
    - `feat: <what was added>`
    - `update: <what file / feature>`
    - `fix: <bug description>`

