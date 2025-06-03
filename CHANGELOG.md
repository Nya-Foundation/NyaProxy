# CHANGELOG


## v0.3.3 (2025-06-03)

### Bug Fixes

- Fix content-encoding/accept encoding issue when dealing with streamed request
  ([`817e9b6`](https://github.com/Nya-Foundation/NyaProxy/commit/817e9b6d3f39e6cdf2566da65336fd534e4e2bca))


## v0.3.2 (2025-06-02)

### Bug Fixes

- Refined and optimized request queue, update config settings and schema, performce optimization
  ([`6e347ff`](https://github.com/Nya-Foundation/NyaProxy/commit/6e347ff1bd4b7e345deb7018276aa0eff1a9b323))

### Chores

- Black format
  ([`6e87482`](https://github.com/Nya-Foundation/NyaProxy/commit/6e87482be10b5769d04895d388543ba8eb851942))

- **format**: Apply automatic formatting [skip ci]
  ([`459c671`](https://github.com/Nya-Foundation/NyaProxy/commit/459c67184668bc588ac545f199e15dd55c5c278b))

- **format**: Apply automatic formatting [skip ci]
  ([`707320f`](https://github.com/Nya-Foundation/NyaProxy/commit/707320f861f14a53621573a618d9f303659c7e48))


## v0.3.1 (2025-06-02)

### Bug Fixes

- Request_body_substitution logic refinement
  ([`b25ca72`](https://github.com/Nya-Foundation/NyaProxy/commit/b25ca7289fbee103041b62cc622529f624a188be))


## v0.3.0 (2025-06-02)

### Features

- Major refactor and architecture re-design, simplify workflow, improve throughput
  ([`d24ff13`](https://github.com/Nya-Foundation/NyaProxy/commit/d24ff131058ad5c6f50029c6b00aa89783dae941))


## v0.2.5 (2025-05-31)

### Bug Fixes

- Bump nekoconf version to 1.1.1
  ([`c239589`](https://github.com/Nya-Foundation/NyaProxy/commit/c23958954b6b39d97e34e490d281df8019872caf))


## v0.2.4 (2025-05-31)

### Bug Fixes

- Add logic to exclude Cloudflare headers
  ([`172cca3`](https://github.com/Nya-Foundation/NyaProxy/commit/172cca3224369625558e6bf11092ee9bbd532955))

- Bump nekoconf version to 1.1.0, remove simulated streaming, add loguru for logging, add support
  for python 3.10
  ([`2043c0f`](https://github.com/Nya-Foundation/NyaProxy/commit/2043c0f3f1bca878b53e448126d76a85655c1331))

### Chores

- Black code format
  ([`61a8707`](https://github.com/Nya-Foundation/NyaProxy/commit/61a8707ad08601f0fe70225904a6470369c5c388))

### Documentation

- Update README.md
  ([`4986383`](https://github.com/Nya-Foundation/NyaProxy/commit/498638336138489908bc1db6d690a87bb4dd2f32))


## v0.2.3 (2025-05-12)

### Bug Fixes

- Fix header processing issue, implement OPTIONS request hijack
  ([`9ad3902`](https://github.com/Nya-Foundation/NyaProxy/commit/9ad3902c9299067a07f4b7c687d8824f5cad580a))


## v0.2.2 (2025-05-12)

### Bug Fixes

- Add cors config support
  ([`f496918`](https://github.com/Nya-Foundation/NyaProxy/commit/f496918d7248ede8ac22754488f3c9a49a95255d))


## v0.2.1 (2025-05-09)

### Bug Fixes

- Patch config ui not save issue, update dashboard and login page logo
  ([`bb01039`](https://github.com/Nya-Foundation/NyaProxy/commit/bb010396e63bb8d7c9e7814a32aad77d1a5b0f3a))

### Chores

- Add PyPI stats
  ([`61681a9`](https://github.com/Nya-Foundation/NyaProxy/commit/61681a98ae5123391ba421c8f38adc72e8f55862))

### Documentation

- Add DeepWiki badge
  ([`a85d88d`](https://github.com/Nya-Foundation/NyaProxy/commit/a85d88dd16300e070b880ebcff0a4824499a5baf))

- Update python version requirements
  ([`b3110e5`](https://github.com/Nya-Foundation/NyaProxy/commit/b3110e54bed39e7d8ffae9a0c1163335b810b356))

- Update README.md
  ([`4346954`](https://github.com/Nya-Foundation/NyaProxy/commit/43469542c91f46947b63a37da4b67fa2a9e6294a))


## v0.2.0 (2025-05-08)

### Bug Fixes

- Upload missing folder... fix test cases
  ([`888356f`](https://github.com/Nya-Foundation/NyaProxy/commit/888356f237e88ad569ea4e26cf3240c5cbef1606))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`dc40648`](https://github.com/Nya-Foundation/NyaProxy/commit/dc40648f66a90c66d1af8df675ade20aaf851edc))

### Features

- Major refactor, support remote config server for central management, drop python 3.9-3.10 support
  ([`546b5c6`](https://github.com/Nya-Foundation/NyaProxy/commit/546b5c60cf19137c7b2c7b32f43c5ba180f85293))


## v0.1.3 (2025-05-03)

### Bug Fixes

- Decompressing logic, bump nekoconf version 0.1.11
  ([`bf89242`](https://github.com/Nya-Foundation/NyaProxy/commit/bf892425864195e05bfa759ad7c4a7cb52de397b))


## v0.1.2 (2025-05-01)

### Bug Fixes

- Fix decompressing logic
  ([`07efb41`](https://github.com/Nya-Foundation/NyaProxy/commit/07efb4125a9ac5fb931b843f7c5b564dd00576c8))


## v0.1.1 (2025-05-01)

### Bug Fixes

- Tune content-encoding logic... attempting to support complex env such as... behindng cloudfare
  proxy -> nginx -> docker
  ([`d2f96be`](https://github.com/Nya-Foundation/NyaProxy/commit/d2f96bedc280398d07d53e2c89fde87f841d400a))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`2d4695c`](https://github.com/Nya-Foundation/NyaProxy/commit/2d4695c4fbe155ed5c5ad40de37b1f1950a56f5a))

- **format**: Apply automatic formatting [skip ci]
  ([`7609dcb`](https://github.com/Nya-Foundation/NyaProxy/commit/7609dcb5c502d87251827c95a3a22c44b89160d4))

### Documentation

- Add doc for docker and pip deployment
  ([`74f8881`](https://github.com/Nya-Foundation/NyaProxy/commit/74f8881550e13935a842b6870e82295196f07006))


## v0.1.0 (2025-04-30)

### Features

- **key**: Multi api_key support, refine README, more test cases
  ([`77f3748`](https://github.com/Nya-Foundation/NyaProxy/commit/77f3748a0a0131d6ac31e8e258afbc4379b8ae4a))


## v0.0.8 (2025-04-30)

### Bug Fixes

- **test**: Fix some minor issue on f-string escpate sequence for backward compatiblities
  ([`c89f862`](https://github.com/Nya-Foundation/NyaProxy/commit/c89f862ea2b5eaccd06a4a08ffcad181a0e7afe4))

### Chores

- **CI**: Remove python 3.14 from unit tests workflow
  ([`1b9468d`](https://github.com/Nya-Foundation/NyaProxy/commit/1b9468d4cad239b9801d672fb00e2621b10ae891))

- **format**: Apply automatic formatting [skip ci]
  ([`c034383`](https://github.com/Nya-Foundation/NyaProxy/commit/c03438366743837866805df0732c1f419e3d5046))

- **README**: Update one-click deploy for Railway
  ([`88bf6b4`](https://github.com/Nya-Foundation/NyaProxy/commit/88bf6b40a2fee015ec430292d2d3212a8e4235df))


## v0.0.7 (2025-04-28)

### Bug Fixes

- Docker startup issue, add one click deploy via render and Railway
  ([`ec6ecae`](https://github.com/Nya-Foundation/NyaProxy/commit/ec6ecae75a4ebca061f40c10525a1dbc998df3af))

### Chores

- **README**: Refine README.md
  ([`053733e`](https://github.com/Nya-Foundation/NyaProxy/commit/053733e238a828976c466a3cb765a322237de093))


## v0.0.6 (2025-04-28)

### Bug Fixes

- **NekoConf**: Bump NekoConf version, refine integration, refine reload logic
  ([`32bc8f2`](https://github.com/Nya-Foundation/NyaProxy/commit/32bc8f2b494115ed91e45a48e2e6fa23a958f3ae))

### Chores

- **CI**: Adjust publish.yml
  ([`56e3f02`](https://github.com/Nya-Foundation/NyaProxy/commit/56e3f0272e4fbe752486faa0cfb13c56355d79ed))

- **CI**: Fix package version #
  ([`0860737`](https://github.com/Nya-Foundation/NyaProxy/commit/0860737c62d8dd4536836f313192b8d86e275e05))

- **format**: Apply automatic formatting [skip ci]
  ([`567c517`](https://github.com/Nya-Foundation/NyaProxy/commit/567c5172f4dd7568db6011a54c922bb8e3b8cbff))

- **format**: Apply automatic formatting [skip ci]
  ([`0109179`](https://github.com/Nya-Foundation/NyaProxy/commit/0109179df2052ca6eeb43879423ce36ef169e822))

- **version**: Bump verion to 0.0.5
  ([`0762eb7`](https://github.com/Nya-Foundation/NyaProxy/commit/0762eb7eb57f21543b2a6bbbb767d392c011e5d0))


## v0.0.5 (2025-04-27)

### Bug Fixes

- Move config.yaml and schema.json into the build folder.. fix build issue
  ([`69fff5b`](https://github.com/Nya-Foundation/NyaProxy/commit/69fff5bfeb079e13cbaba999c2d07a4cf5bd57e6))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`5ad007c`](https://github.com/Nya-Foundation/NyaProxy/commit/5ad007c6f1f7e2ee5b02329a644f5ac8af5851c2))

- **README**: Fix README error
  ([`0b1c4b2`](https://github.com/Nya-Foundation/NyaProxy/commit/0b1c4b21c623b61a0e24227b52811f3c6e13c099))

- **README**: Update README.md user guide
  ([`3b1b05c`](https://github.com/Nya-Foundation/NyaProxy/commit/3b1b05c755e78e1b85139999a7d8b37c155cff1e))


## v0.0.4 (2025-04-27)

### Bug Fixes

- Adjust image size
  ([`9d4386a`](https://github.com/Nya-Foundation/NyaProxy/commit/9d4386affd4b5407df0a1860df047eb690382189))

### Chores

- **README**: Update README.md file, add project banner image, update discord link, fix pypi upload,
  bump version to v0.0.4
  ([`d9a70ee`](https://github.com/Nya-Foundation/NyaProxy/commit/d9a70ee546811b2336de81c63dccbf438d1d6a5f))


## v0.0.3 (2025-04-27)


## v0.0.2 (2025-04-27)


## v0.0.1 (2025-04-27)

### Bug Fixes

- Fix broken stream request, response encoding handling; feature: add Ignore path config logic,
  exclue certain path from being record as key usage rate and limit exclusion
  ([`d31553e`](https://github.com/Nya-Foundation/NyaProxy/commit/d31553e86e7d2581f109787257bd2262eb33fac4))

- Resolve conflict
  ([`187d23a`](https://github.com/Nya-Foundation/NyaProxy/commit/187d23a566cfb3751985b6cb9a7c1c88b419c2db))

- Resolve conflict
  ([`2bd8457`](https://github.com/Nya-Foundation/NyaProxy/commit/2bd8457f9143f07a27b67be6cc1abee3337124e9))

- **ci**: Ad step to upload pypi, fix dependency-review.yml, bump version to v0.0.3
  ([`ecc50d9`](https://github.com/Nya-Foundation/NyaProxy/commit/ecc50d955ad8f5f39b577e359b258f183fb13bc2))

- **ci**: Fix pyproject.toml [dev] optional-dependencies
  ([`cdf6978`](https://github.com/Nya-Foundation/NyaProxy/commit/cdf6978bd739011760c58c71bac1bc9db26ef8cf))

- **ci**: Fix test.yml pytest issue
  ([`6a46b12`](https://github.com/Nya-Foundation/NyaProxy/commit/6a46b12e8ddd46e751e62ea43b4ee4c987aa0acd))

- **major**: Retry config consolidation, retry logic handling, metrics timeout issue, rate limit
  queue fix
  ([`4bb2773`](https://github.com/Nya-Foundation/NyaProxy/commit/4bb277337b3b49b0331050d89055365b4e7ba69a))

- **security**: Remediate 2 critial vulnerabilities, optimize Dockerfil, reduce image size with
  Alpine, fix config_path priority issue, fix pypi upload logic in ci, fix pyproject.toml format
  issue
  ([`ba1f338`](https://github.com/Nya-Foundation/NyaProxy/commit/ba1f33894acaa2a60256c1463cf94e2d0923168c))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`9829453`](https://github.com/Nya-Foundation/NyaProxy/commit/98294531c352f2fc72fb6f4dbd3f6303f27c5cdc))
