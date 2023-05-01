#!/bin/bash

# test only the diff against master

diff_files=$(git diff --name-only master..HEAD | xargs -n1 basename)

pattern=".*($(echo "$diff_files" | tr '\n' '|' | sed 's/.$//')).*"

python manage.py test --pattern="test_*{pattern}*"




# name: Django CI
# 
# on:
#   pull_request:
#   push:
# 
# jobs:
#   test:
#     runs-on: ubuntu-latest
# 
#     steps:
#       - uses: actions/checkout@v2
# 
#       - name: Install dependencies
#         run: pip install -r requirements.txt
# 
#       - name: Run tests
#         run: |
#           if [[ -n $(git diff --name-only ${{ github.base_ref }}..${{ github.head_ref }}) ]]; then
#             python manage.py test --pattern="test_*{changed_file_name}*"
#           else
#             python manage.py test
#           fi


