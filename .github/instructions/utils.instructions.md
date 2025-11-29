# Utils Folder Instructions

Utility modules should:
- Remain pure helpers.
- Avoid circular dependencies.
- Expose stable, reusable functions.

File access logging, config helpers, and common utilities belong here.

Avoid embedding business logic in utils. Route complex behavior to controllers/pipelines.