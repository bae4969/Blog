## PHP Blog – AI Coding Agent Guide

Purpose: Give AI agents the minimum, concrete context to be productive here.

### Big Picture
- MVC structure with PSR-4 autoloading (`Blog\` → `src/`). Single web entry at `public/index.php`.
- Core layers: `src/Core` (framework utilities), `src/Controllers`, `src/Models`, `src/Database`, and `views/`.
- Router is minimal and file-based; controllers render PHP views with shared layouts. HTML is sanitized before persistence.
- Performance: app-wide in-memory + file cache with explicit invalidation patterns; DB wrapper logs queries and exposes stats.

### Key Files
- Router: `src/Core/Router.php` (adds routes, supports `:id` params, optional route pattern passed as handler[2]).
- Controllers base: `src/Controllers/BaseController.php` (render helpers, input sanitize, CSRF, JSON/redirect, session/auth wrappers).
- Views: `src/Core/View.php` (render, layout render, `csrfToken()`, `escape()`), templates in `views/` and `views/layouts/`.
- DB: `src/Database/Database.php` (PDO, `fetch`, `fetchAll`, `query`, query log + `getQueryStats()`/`getQueryLog()`).
- Cache: `src/Core/Cache.php` (`get/set/delete/deletePattern/clear`, `key(prefix, ...)`, TTLs via `config/cache.php`).
- Sanitizer: `src/Core/HtmlSanitizer.php` and HTMLPurifier usage in `src/Models/Post.php::create()`.

### Routing Conventions
- Define routes in `public/index.php` using `$router->get()`/`post()`.
- Path params: use `:id` style and pass the route template as 3rd handler arg when you need extraction, e.g.:
  `$router->get('/post/edit/:id', [PostController::class, 'editForm', '/post/edit/:id']);`
- Legacy endpoints are preserved (`/login.php`, `/reader.php`, `/writer.php`) alongside pretty paths.

### Controller Conventions
- Extend `BaseController`; prefer `renderLayout('main', 'home/index', $data)` for pages.
- Always validate CSRF on POST: `if (!$this->validateCsrfToken()) { ... redirect(...) }` and pass `csrfToken` to views.
- Sanitize scalar inputs with `sanitizeInput()`. Use `validateRequired($data, $fields)` for required fields.
- Auth helpers: `auth->requireLogin()` and `auth->requireWritePermission()`; `Auth` gets/guards session state.

### Model + Cache Patterns
- Get DB via `Database::getInstance()`; never instantiate PDO directly.
- Build cache keys with `Cache::key('prefix', $parts...)`. Cache read-heavy queries; skip cache for dynamic searches.
- Invalidate on mutation using broad patterns, e.g. posts: `deletePattern('posts_meta')`, `deletePattern('post_detail')`, `deletePattern('post_count')`.
- TTLs live in `config/cache.php` under `cache_ttl`; use them when appropriate.

### HTML Safety
- For user content, sanitize HTML (HTMLPurifier). See `Post::create()` for allowed tags and serializer cache dir.
- For plain text, `View::escape()` before output if not already sanitized.

### DB Access & Perf
- All queries go through `Database` (prepared statements enforced). Slow query threshold defaults to 100ms and logs to error_log.
- Perf APIs available via `PerformanceController` (query stats, slow/duplicate queries) and `CacheController` (stats/clear/warmup). Add routes in `public/index.php` if you expose them.

### Local Dev & Scripts
- PHP 7.4+. Install deps: `composer install`. Frontend (optional): `npm install` (Quill editor is vendored in `public/vendor/quill/`).
- Quick run (built-in server): `php -S localhost:8080 -t public` then open `/index.php`.
- Tests: `composer test` and `composer test-coverage` (only if a `tests/` suite is present).
- Configure DB in `config/database.php`; cache dir is `cache/data` (create and ensure writable).

### Example: Add a page
1) Controller method in `src/Controllers/NewController.php` extending `BaseController` and calling `renderLayout('main', 'path/to/view', [...])`.
2) Route in `public/index.php`: `$router->get('/new', [NewController::class, 'index']);`
3) View at `views/path/to/view.php`; include `<?= $view->csrfToken(); ?>` if form POSTs.

### Gotchas
- Category permissions compare with `>=` (smaller `user_level` = higher privilege). See checks in `Category` and `Post`.
- Search results are intentionally not cached; lists and counts are.
- Read and visitor counters use session keys to limit increments; clearing sessions affects counts.
- When adding mutations, remember to invalidate related cache patterns from `config/cache.php`.
