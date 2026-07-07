---
name: worktree-refactor
description: Use git worktree isolation to refactor code safely without affecting the main branch. Ideal for complex refactoring tasks.
---

# Worktree Refactor Skill

Use this skill when the user asks to refactor code, restructure a project, or make significant changes that should be isolated from the main branch.

## Workflow

1. **Create a task** for the refactoring work:
   - Use `create_task` with a clear subject and description

2. **Create an isolated worktree**:
   - Use `create_worktree(name="refactor-{topic}", task_id="{task_id}")`
   - This creates a branch `wt/refactor-{topic}` and an isolated directory

3. **Assign to a teammate** (if the task is complex):
   - Use `spawn_teammate` to create a specialized teammate
   - Tell them the worktree path
   - The teammate works ONLY in the worktree directory

4. **Wait for completion**:
   - Teammate writes changes in the isolated worktree
   - Task is marked as completed

5. **Merge the worktree**:
   - Use `merge_worktree(name="refactor-{topic}")` to merge the branch into main
   - If merge conflicts occur, resolve them manually or use `keep_worktree` for review

6. **Clean up**:
   - Use `remove_worktree(name="refactor-{topic}")` if merge was successful
   - Or use `keep_worktree(name="refactor-{topic}")` if you want to review first

## Key Principles

- **Isolation**: All refactoring happens in the worktree, main branch stays clean
- **Atomic**: One refactoring topic per worktree
- **Reviewable**: Use `keep_worktree` to pause and review before merging
- **Clean**: Always remove worktrees after merging

## Example

User: "Refactor the todo app to separate frontend and backend"

1. `create_task(subject="Refactor todo app: separate frontend and backend")`
2. `create_worktree(name="todo-app-refactor", task_id="{task_id}")`
3. `spawn_teammate(name="refactorer", role="full-stack developer", prompt="Separate the todo app into frontend and backend...")`
4. Wait for completion
5. `merge_worktree(name="todo-app-refactor")`
6. `remove_worktree(name="todo-app-refactor")`
