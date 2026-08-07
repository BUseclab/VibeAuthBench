# VibeAuthBench

### Benchmarking Large Language Model (LLM) Agents on Secure Code Generation

Yash Parikh<sup>1,2</sup>, Gianluca Stringhini<sup>2</sup>, Manuel Egele<sup>2</sup>

<sup>1</sup> Del Norte High School, San Diego, CA 92127; <sup>2</sup> Boston University, Boston, MA 02215

## Abstract

Previous security benchmarks for LLM-generated code often focus on creating and evaluating small code snippets in context-free scenarios, disregarding how LLM agents are actually used in practice: in an existing, complex application and asked by a developer to modify or add entire functionalities. Benchmarks that do test real repositories have focused on a single language, which doesn't show whether performance generalizes across languages. We present VibeAuthBench (VAB), a benchmark that evaluates misconfigurations and vulnerabilities introduced by AI coding agents implementing features into existing software. VAB provides a two-stage pipeline: an agent's implementation of a given feature request is first checked for functionality, then analyzed by a separate LLM-as-judge for introduced security vulnerabilities, creating a benchmark score for each run. We demonstrate VAB through the task of implementing Sign-In with Google (Google OAuth) into three open-source applications with Go, Python, and Node.js backends that did not yet support OAuth/OIDC-based login, across 30 runs of two open-weight models. The agents generally provided the instructions needed for a developer to finish the integration, but produced a working end-to-end sign-in flow in only 5 of 30 runs. Of 172 security findings, 163 were introduced by the new code. Average VAB scores, where lower indicates fewer and less severe findings, ranged from 23.14 to 39.71 across model and backend configurations, with both models scoring best in the Python codebase and substantially worse in Go and Node.js, suggesting that agent security behavior varies across languages. As such, we aim to establish a modular pipeline for benchmarking models and harnesses across a variety of feature requests and base applications.

## This repository

The code here is the experiment pipeline used to produce the results described above.

| | |
| --- | --- |
| `experiment.py` | Runs the integration task in a container, per app and model |
| `entrypoint_auto.py`, `entrypoint_manual.py` | In-container phases: the agent's task, then functional verification |
| `prompt_loader.py`, `prompts.json` | Builds the task prompt from a per-app template and credentials in `.env` |
| `show_completion.py` | Prints each run's final agent message, to check whether it named a redirect URI |
| `security_eval.py` | Runs the verifier agent against the resulting codebase |
| `security_rubric.md` | Scope and output format given to the verifier |
| `aggregate_findings.py`, `model_score.py` | Summarize findings across runs |
| `rubric_ref_normalize.py` | Normalizes the verifier's rubric citations so counts aggregate consistently |
| `Dockerfile.*` | Per-application build environments |

Target application sources and collected run data are not included.

`OWASP_OAuth2_Cheat_Sheet.md` and `Google_OAuth2_BestPractices.md` are third-party
documents included under their own licenses - see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Running this

`bases/<app>-base/` must exist before anything else: the Dockerfiles `COPY` from it, and
`security_eval.py` reconstructs each run against it.

```bash
mkdir -p bases
git clone https://github.com/traggo/server        bases/traggo-base
git -C bases/traggo-base           checkout 6321119c3c2d55f04e2e4967f6492aabd6067b76

git clone https://github.com/bhj/KaraokeEternal   bases/karaoke-eternal-base
git -C bases/karaoke-eternal-base  checkout b209d4a90aee03420eed5c14d0552b56bd7f89c5

git clone https://github.com/babybuddy/babybuddy  bases/babybuddy-base
git -C bases/babybuddy-base        checkout 16b8848c7bc2031fc5936f8da89c8056ec5624d2
```

| App | Upstream | Commit | License |
| --- | --- | --- | --- |
| traggo | [traggo/server](https://github.com/traggo/server) | `6321119c` (2026-03-01) | GPL-3.0 |
| karaoke-eternal | [bhj/KaraokeEternal](https://github.com/bhj/KaraokeEternal) | `b209d4a9` (2026-02-14) | ISC |
| babybuddy | [babybuddy/babybuddy](https://github.com/babybuddy/babybuddy) | `16b8848c` (2026-06-07) | BSD-2-Clause |

Then build the images and set up credentials:

```bash
cp .env.example .env      # fill in a Google OAuth client ID and secret
docker build -f Dockerfile.traggo          -t vab-traggo          .
docker build -f Dockerfile.karaoke-eternal -t vab-karaoke-eternal .
docker build -f Dockerfile.babybuddy       -t vab-babybuddy       .
docker build -f Dockerfile.security-judge  -t vab-security-judge  .
```

Two external requirements: the app images point Claude Code at an Anthropic-compatible endpoint on
`http://localhost:1618`, which is where the model under test is served; and the judge needs
`CLAUDE_CODE_OAUTH_TOKEN` in `.env` (created with `claude setup-token`).

`runs/` and `_security_workdir/` are created automatically as needed.

```bash
python3 experiment.py launch <app> <model>    # agent performs the feature integration
python3 experiment.py finish                  # you verify the login flow is functional
python3 security_eval.py run --all            # judge reviews the code for security
python3 aggregate_findings.py                 # aggregate findings across runs
```

Linux only note: the containers use `--network host`, and `experiment.py` uses `fcntl`. Every `docker` call is issued as `sudo docker` to avoid permission issues.

LLM Usage Note: Claude Code was used as a coding assistant to implement the VibeAuthBench framework from the authors' design. This documentation was also structured and polished with the assistance of Claude Code.

## Acknowledgements

I would like to thank Professor Gianluca Stringhini and Professor Manuel Egele for the opportunity to work with them at SeclaBU, for helping ideate and progress this study, and for their consistent mentorship throughout the research. I would also like to thank Khosro Moeini for his supervision in the lab and support with my numerous questions.

## References

[1] C. Tony, M. Mutas, N. E. D. Ferreyra, and R. Scandariato, ‘LLMSecEval: A Dataset of Natural Language Prompts for Security Evaluations’, in 2023 IEEE/ACM 20th International Conference on Mining Software Repositories (MSR), 2023, pp. 588–592, doi:10.1109/MSR59073.2023.00084.

[2] S. Zhao, D. Wang, K. Zhang, J. Luo, Z. Li, and L. Li, ‘Is Vibe Coding Safe? Benchmarking Vulnerability of Agent-Generated Code in Real-World Tasks’, 2026, arXiv: 2512.03262v2.

[3] J. Chen et al., ‘SecureVibeBench: Benchmarking Secure Vibe Coding of AI Agents via Reconstructing Vulnerability-Introducing Scenarios’, 2026, arXiv: 2509.22097.

[4] C. Shen, C. Dilgren, P. Chiniya, L. Griffith, Y. Ding, and Y. Chen, “SecRepoBench: Benchmarking Code Agents for Secure Code Completion in Real-World Repositories,” Proceedings of the 3rd International Workshop on Large Language Models For Code. ACM, pp. 159–166, Apr. 12, 2026. doi: 10.1145/3786181.3788703.

[5] Qwen Team, “Qwen3 Technical Report,” 2025, arXiv: 2505.09388.

[6] Qwen Team, “Qwen3.6-27B: Flagship-Level Coding in a 27B Dense Model,” Apr. 2026. [Online]. Available: https://qwen.ai/blog?id=qwen3.6-27b.

[7] Claude Code. (2026). Anthropic. [Online]. Available: https://code.claude.com/.

[8] “babybuddy”, 2026. [Online]. Available: https://github.com/babybuddy/babybuddy. 

[9] “traggo”, 2026. [Online]. Available: https://github.com/traggo/server. 

[10] “karaoke-eternal”, 2026. [Online]. Available: https://github.com/bhj/KaraokeEternal/. 

[11] OWASP, “OAuth 2.0 Protocol Cheatsheet,” May 7, 2026. [Online]. Available: https://cheatsheetseries.owasp.org/cheatsheets/OAuth2_Cheat_Sheet.html.

[12] “Best Practices,” Google LLC, May 20, 2026. [Online]. Available: https://developers.google.com/identity/protocols/oauth2/resources/best-practices.

[13] Common Vulnerability Scoring System version 4.0, Forum of Incident Response and Security Teams, Inc., Nov. 1, 2023. [Online]. Available: https://www.first.org/cvss/v4.0/specification-document. 