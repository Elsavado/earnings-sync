<!-- markdownlint-disable MD013 MD043 -->

# Ever IRTranscripts documentation

The Ever IRTranscripts documentation does not live in this repository. It is written in
[`ever-co/ever-gauzy-docs`](https://github.com/ever-co/ever-gauzy-docs) and published at
**[docs.irtranscripts.com](https://docs.irtranscripts.com)**. This folder only points there.

## Read

| What                            | Where                                                                                                     |
| ------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 📖 **Platform documentation**   | **[docs.irtranscripts.com](https://docs.irtranscripts.com)**                                                                |
| 🚀 Quick start                  | [docs.irtranscripts.com/getting-started/quick-start](https://docs.irtranscripts.com/getting-started/quick-start/)           |
| 🛠️ Installation                 | [docs.irtranscripts.com/getting-started/installation](https://docs.irtranscripts.com/getting-started/installation/)         |
| 📡 API overview                 | [docs.irtranscripts.com/api/overview](https://docs.irtranscripts.com/api/overview/)                                         |
| 🧪 Live API reference (Swagger) | [api.irtranscripts.com/docs](https://api.irtranscripts.com/docs)                                                            |
| 🚢 Deployment (Kubernetes)      | [docs.irtranscripts.com/deployment/kubernetes](https://docs.irtranscripts.com/deployment/kubernetes/)                       |
| 🐳 Deployment (Docker Compose)  | [docs.irtranscripts.com/deployment/docker/docker-compose](https://docs.irtranscripts.com/deployment/docker/docker-compose/) |
| 💻 Contributing to IRTranscripts        | [docs.irtranscripts.com/development/contributing](https://docs.irtranscripts.com/development/contributing/)                 |
| 📚 Wiki                         | [github.com/ever-co/ever-gauzy/wiki](https://github.com/ever-co/ever-gauzy/wiki)                          |

## Use

| What                        | Where                                            |
| --------------------------- | ------------------------------------------------ |
| 🌐 Website                  | [irtranscripts.com](https://irtranscripts.com)                     |
| ⬇️ Downloads (server, apps) | [irtranscripts.com/downloads](https://irtranscripts.com/downloads) |
| ☁️ Ever IRTranscripts SaaS          | [app.irtranscripts.com](https://app.irtranscripts.com)             |
| 🎮 Demo (resets daily)      | [demo.irtranscripts.com](https://demo.irtranscripts.com)           |

## Write or fix a page

Open a pull request in **[`ever-co/ever-gauzy-docs`](https://github.com/ever-co/ever-gauzy-docs)**, not here:

- the site is a [Docusaurus](https://docusaurus.io/) app in `website/`; the pages are Markdown under
  `website/docs/`, one folder per section of the sidebar;
- base the pull request on `develop` (`master` is what docs.irtranscripts.com publishes);
- run it locally with `yarn install` then `yarn start` in `website/`.

A page that would have gone in `docs/<section>/` of this repository goes in `website/docs/<section>/` there.
Every page on docs.irtranscripts.com has an "Edit this page" link to its source.

## Pages that used to be here

These two pages are generated from code in this repository, and a CI check fails when a page drifts from
that code, so the copy the check reads stays beside its generator under `tools/`. The published page is a
copy of it; regenerate the copy here, then copy the change to the docs repository.

| Was                                              | Published at                                                                                                          | Copy checked by CI here                                                                                                                     |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/ever-platform/outbound-calls.md`           | [docs.irtranscripts.com/ever-platform/outbound-calls](https://docs.irtranscripts.com/ever-platform/outbound-calls/)                     | [`tools/ever-platform/outbound-calls.md`](../tools/ever-platform/outbound-calls.md) (`node tools/ever-platform/outbound-calls.mjs --check`) |
| `docs/platform-extensions/design-name-triage.md` | [docs.irtranscripts.com/platform-extensions/design-name-triage](https://docs.irtranscripts.com/platform-extensions/design-name-triage/) | [`tools/scripts/design-name-triage.md`](../tools/scripts/design-name-triage.md) (`node tools/scripts/design-name-triage-check.mjs`)         |
