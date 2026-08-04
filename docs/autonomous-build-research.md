# Letting an agent fleet build a product

**v0.2**

*Agents build single components well and fail to connect them, so everything that makes an unattended run succeed is done beforehand: hidden tests written by someone other than the builders, components with interfaces you own, and machine checks that replace reading every diff.*

## What to expect

Three days of unattended work will not produce a correct product. The reason is not the model. A current model works reliably for a couple of hours at a stretch, so three days is dozens of stretches chained end to end, and small errors compound across them.

What three days does produce, reliably, is a system that builds, runs, demos, and passes its own tests, with most individual components working. The gap is between them. Roughly a third of what one component offers is actually used by the component that was supposed to use it. Everything looks finished and the system does not work.

So plan for it. The run gives you the components. Your remaining work is the wiring and the correctness, and that is where your days go. Anyone promising otherwise is selling something.

## The four things that make it work

**One. The tests are written by a different agent, corrected by you, and hidden from the builders.**

Agents that write their own tests write tests their own code passes. So one agent writes the fourteen day journeys, you correct them, and the agents doing the implementation never see the code.

Publish the fourteen days as prose. The builders should know what day four is about. Hiding the description as well makes things worse, because then they are building against a contract they cannot read.

Hide the test output too, not just the test code. If a journey fails and the builders can see the stack trace, the failing element, the screenshot, then every failure hands them one more assertion, and over three days they reconstruct the hidden tests from the error messages. The journeys run somewhere the fleet cannot reach, and what comes back is a number: nine of fourteen.

Then prove the journeys work before the run starts. Plant one deliberate bug per journey and confirm each journey catches its own. A journey that accidentally asserts almost nothing will pass forever, and you would read that as success. Half a day of your time, and it protects the one thing nothing else protects.

**Two. The product splits into components, and you own the interfaces between them.**

A picture of the architecture is not the deliverable, because nothing can check a picture. Two things need to exist in a form a machine can read.

The dependency direction: which components may import which. Decided once, then enforced automatically, so architectural drift becomes a failed merge instead of an argument.

The interfaces themselves: the shapes components pass to each other. You write these, not the fleet. If an agent writes an interface and gets one field wrong, every component typechecks perfectly against that mistake and the compiler reports success for three days. The interfaces are small and writing them is cheap. They are worth more than the diagram.

Then one change to the gate we already have. Today a requirement names the component that implements it. Make it name two: the component that implements it and the component that uses it. Now a machine can ask "was this built and never connected" and answer on every merge instead of on day four. That is the single highest value half day in this plan.

**Three. Machine checks instead of reading every merge.**

Reviewing every merge request is too expensive and buys little: agent review of agent work catches under a third of deliberately planted mistakes. Skip it.

But something has to take its place, because "the tests pass" will not. A stub in the right folder with the right annotation and a test that checks a mock was called passes every other gate.

The replacement is a set of checks that run in seconds, cost nothing, and need none of your time. The next section explains the kind of check that does most of the work, and the list is further down.

**Four. The specifications and the Definition of Done, exactly as we built them for the ERP.**

Not optional, and not changed. The journeys have to be journeys of something. The two component binding needs identifiers to bind. The gate needs a declared list to check against. That contract is what makes everything above possible.

## What a threshold check is

A threshold check is a number the machine computes from the source code without running it, plus a line that number may not cross. Cross the line and the merge fails. No opinion, no judgement, nobody reading anything.

Real examples:

- **Complexity.** Count the decision points in a function: every `if`, every loop, every `and` or `or`. If any function scores above ten, fail. A function with thirty branches is one nobody can safely change later.
- **Volume.** Total lines of code against a budget you set at the start. Agents solve problems by adding code, so this is the only check that pushes back on growth.
- **Duplication.** The percentage of the codebase appearing as near identical blocks elsewhere. Above about five percent, fail. This is what catches an agent copying a file instead of reusing one.
- **Coupling.** How many other modules one file reaches into. A file importing twenty others breaks when any of them changes.
- **Raw values.** Zero literal colours or pixel numbers outside your token file. The threshold is zero, which makes it the easiest to enforce and the reason the interface stays consistent.

Four properties make this the right substitute for review. It reads text and runs nothing, so it never flakes and never gives a different answer twice. It takes seconds. An agent cannot argue with it or talk it round. And it produces a plain number, so you watch the trend across the run instead of a pass or fail.

Its weakness is real and worth stating plainly: a threshold check measures the shape of the code and never whether the code does the right thing. It does not replace the journeys. It replaces a human reading the diff, which is exactly the job you do not want to pay for.

Set every line where ordinary good projects already sit, not at perfection. A threshold nobody can meet gets switched off in week two, and then you have neither the check nor the review.

Without some version of this, nothing pushes back on the code getting worse. An independent audit of one week long fully autonomous build scored it in the bottom five percent of all systems for maintainability. That is the default outcome, not bad luck.

## What you produce before pressing go

Eleven items. This is the week of work that buys the unattended run.

1. **The specifications and the Definition of Done**, locked, by the method we already have.
2. **The component split and the dependency direction.** Which components exist, and which may depend on which.
3. **The interfaces between components.** Yours, not the fleet's, for the reason above.
4. **The fourteen day journeys, twice.** As prose, published to everyone. As code, written by a separate agent, corrected by you, proven against a planted bug, and never visible to a builder.
5. **The seed data.** Specific rows, edge values, empty states, awkward names. The same every run, or "it passed twice" means nothing.
6. **The design tokens.** Named colours, spacings, and type sizes with their actual values, so reviewing the interface becomes a check instead of a matter of taste.
7. **The negative space.** What the product must never do. Fourteen journeys are fourteen things going right, and nothing else here covers the things that must not happen.
8. **The build order.** What gets built first. Models are measurably poor at this and it is cheap for you.
9. **The blast radius.** What agents may never touch: the tests, the gate, the tool configuration, credentials, anything live.
10. **The budget and the abort conditions.** An agent asked whether to keep going says yes. A spend cap that actually halts, and the conditions under which you stop.
11. **One check that is not about behaviour.** Strict types, schema conformance, or accessibility assertions. A test suite only ever sees the behaviours somebody thought to write down.

## The machine checks, in one list

| Check | What it catches | Your cost |
|---|---|---|
| A requirement binds an implementer and a user | built but never connected, the main failure | half a day, once |
| Dependency direction | architectural drift | half a day, once |
| Complexity, volume, duplication, coupling thresholds | code getting worse where nobody is looking | a day, once |
| Only named tokens, no raw values | an interface drifting off the design | an hour |
| Every package named actually exists | invented dependencies, a real and measured risk | an hour |
| A decision log, and a merge rejected when it claims no decisions were made | the hundreds of small choices the specifications did not settle | nearly free |
| The declared registry check | a requirement quietly losing its owner | already built |

The decision log is the one to notice. Every work item appends the choices it made that the specifications did not determine, and a work item claiming it made none is rejected, because none is a lie. That file is what you read on day four instead of reading diffs.

## How you know on day one

Before any agent runs, the gate should be **red** on the empty repository. If an empty repository passes, the checks are measuring nothing and little after that tells you much.

Then walk the riskiest journey by hand on the skeleton. If you cannot, the fleet will not either.

At the end of day one, run the hidden journeys against whatever has passed its own tests. The gap between "passes its own tests" and "passes yours" is the most useful number in the exercise, you get it on day one, and if it is already wide then three more days makes it wider rather than narrower.

## Stop the run if

A planted bug gets through a journey, because every green result since the last good check is now meaningless. Evidence appears that no journey run produced. Anything writes to a protected path. Two consecutive work items connect nothing new. The volume budget is exceeded, in which case cut scope rather than raising the cap.

## Decisions for you

1. **Do the day journeys block every merge, or only final acceptance?** Only acceptance. They are slow and they flake, and a check that cries wolf gets switched off. The fast machine checks block merges.
2. **Do you correct all fourteen journeys yourself?** Yes, two to three days. This is the one thing that cannot be delegated to the thing being tested.
3. **Where do the hidden journeys live?** A separate repository the fleet cannot read, returning only a count.
4. **What is the volume budget?** Pick a number now. It is the only check that opposes growth, and it is worthless if set after you have seen the result.

## Where the evidence sits

Every claim above came from a research sweep whose full findings, sources, and the numbers behind them are kept out of this document deliberately. If you want to check a specific claim, ask for that one and I will give you the source. The two that carry the most weight, and that I would want questioned: components come out individually fine and fail to connect, and agent review of agent work catches well under half of planted mistakes.
