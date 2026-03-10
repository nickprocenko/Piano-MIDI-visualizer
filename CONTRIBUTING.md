# Contributing to Piano MIDI Visualizer

Thank you for your interest in helping out! This guide will get you up and running as quickly as possible.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting the Code](#getting-the-code)
3. [Development Setup](#development-setup)
4. [Project Layout](#project-layout)
5. [Making Changes](#making-changes)
6. [Submitting a Pull Request](#submitting-a-pull-request)
7. [Style Guide](#style-guide)

---

## Code of Conduct

Be kind and constructive. We are here to build something fun together.

---

## Getting the Code

```bash
# Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/Piano-MIDI-visualizer.git
cd Piano-MIDI-visualizer

# Add the upstream remote so you can pull future changes
git remote add upstream https://github.com/nickprocenko/Piano-MIDI-visualizer.git
```

---

## Development Setup

1. **Install Node.js 18 LTS** (or newer) from https://nodejs.org/
2. Install project dependencies:
   ```bash
   npm install
   ```
3. Copy the example config and adjust it for your setup:
   ```bash
   cp config.example.json config.json
   ```
4. Start the development server (auto-restarts on file changes):
   ```bash
   npm run dev
   ```
5. Open **http://localhost:3000** in your browser.

---

## Project Layout

```
src/
  client/         HTML + CSS + canvas renderer that runs in the browser
  server/         Node.js process that captures MIDI and serves the client
docs/             Design notes, screenshots, and architecture diagrams
```

A good starting point is `src/server/index.js` for the backend and
`src/client/visualizer.js` for the rendering logic.

---

## Making Changes

1. Create a new branch from `main`:
   ```bash
   git checkout main
   git pull upstream main
   git checkout -b feature/my-awesome-thing
   ```
2. Make your changes and test them locally.
3. Commit with a clear message:
   ```bash
   git commit -m "feat: add neon colour theme"
   ```
4. Push your branch:
   ```bash
   git push origin feature/my-awesome-thing
   ```

### Commit message format

We follow a simplified [Conventional Commits](https://www.conventionalcommits.org/) style:

| Prefix | When to use |
|--------|-------------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `style:` | Formatting, no logic change |
| `refactor:` | Code restructure, no behaviour change |
| `chore:` | Build scripts, config, dependencies |

---

## Submitting a Pull Request

1. Open a Pull Request against the `main` branch on GitHub.
2. Fill in the PR template – describe *what* you changed and *why*.
3. Link any related issues with `Closes #<issue-number>`.
4. Wait for a review. We'll do our best to respond quickly!

---

## Style Guide

- **Indentation**: 2 spaces (no tabs)
- **Quotes**: single quotes for JavaScript strings
- **Semicolons**: always
- **Variable declarations**: prefer `const`, use `let` when reassignment is needed; avoid `var`
- **Comments**: write comments for non-obvious logic; keep them concise

Running `npm run lint` will catch most style issues automatically.
