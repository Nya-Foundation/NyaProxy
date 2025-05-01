# CHANGELOG


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
