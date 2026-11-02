# Working conventions for this repo

## Pull requests

Open a pull request by default after pushing a completed branch — don't
wait to be asked. Skip it only when the user says otherwise for that piece
of work (e.g. "just push, no PR yet") or the branch isn't actually done.

Once opened, merge it automatically too — don't wait for a separate
"merge it" instruction. Skip auto-merging only when the user says
otherwise for that piece of work, when tests/build aren't passing, or when
the change is large/risky enough to warrant a look first.

## Git
- When the work is done, commit and push to main. Never leave a branch
  or pull request for me to merge – I don't review code.
- If you worked on a side branch, merge it into main and push main
  before you finish.
- Before pushing, run this repo's tests or checks. If they fail, fix
  them. If you can't, don't push to main, and tell me why.
- If main publishes a website, check the change at phone width first.
