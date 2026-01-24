## Development automation

## Github action
### What is github action?
Github action is a development automation tool, with which CI/CD can be built.

### What are developer workflows? 
Common development workflows:
1. organizational tasks:
2. issues
3. pull requests
4. merge PR
5. release after merging (CI/CD)

### Basic Concepts of GitHub Actions
How GitHub Actions automates those workflows? GitHub Events & Actions

Actions happen when something happens to the repository:
1. PR
2. Merge
3. Issue
4. Contributor join

Actions trigger workflows to automate the tasks:
1. Sort
2. Label
3. Assign
4. Reproduce
5. Test

### GitHub Actions CI/CD
https://github.com/actions

### Why another CI/CD Tool
Benefits of Github Actions

### Create CI Workflow or Pipeline
Syntax of Workflow File
- name
- on
- jobs
  - steps
    - uses
    - run

Where does this Workflow Code run? GitHub Action Runner
- Each job is run in its own virutal machine
- Jobs are run in parallel by default. Use needs to override it:
  jobs:
    build:
      runs-on: ubuntu-latest
      steps:
        - uses: ...
        - name: ...
          run: ...
    publish:
      needs: build

If we want to run the build on multiple OS, we need to use strategy:
  jobs:
    build:
      runs-on: ${{matrix.os}}
      strategy:
        matrix:
          os: [ubuntu-latest, windows-latest, macOS-latest]

Build Docker Image and push to private Docker Repo
