---
schema: milestone/1
architecture: 1
mvp: false
satisfies: [I7, I8]
---

# 02: Keyboard control

**Goal.** A user can switch a session to read-only or plan from the keyboard in the Desktop app, and can rebind those keys and bind `writable` in Settings without editing a file.

**Exit.** With the desktop focused and a chat open: `Ctrl+Alt+R` fills the read-only pill, `Ctrl+Alt+P` fills the plan pill, and Settings → Keybinds lists all three actions under "Read-only guard" with `writable` showing no binding.

**Out of scope.** OS-global hotkeys; a cycle-mode key; keybinds in the CLI, TUI, gateway or a browser client — those surfaces expose `/readonly` instead, because the desktop keybind registry is not available to them.

## Features

F1: a user can switch the focused session to read-only with a keystroke
F2: a user can switch the focused session to plan with a keystroke
F3: a user can bind `writable` to a key of their own, and it ships unbound
F4: a user can rebind any of the three in Settings and have it survive a restart
F5: a user reading the README can tell which surfaces have keybinds, and what to use on the others

## Tickets
