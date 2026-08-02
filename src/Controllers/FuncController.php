<?php

namespace Blog\Controllers;

use Blog\Core\Cache;
use Blog\Core\Logger;
use Blog\Core\YouTubeConfig;
use Blog\Core\GeminiConfig;
use Blog\Core\OpenAiConfig;
use Blog\Core\AiProviderConfig;
use Blog\Services\YouTubeFeedService;
use Blog\Services\GeminiAnalysisService;
use Blog\Services\OpenAiAnalysisService;
use Blog\Models\FuncAnalysis;
use Blog\Database\Database;

class FuncController extends BaseController
{
    private function getFuncMenuItems(): array
    {
        return [
            [
                'key' => 'youtube-feed',
                'label' => 'Youtube 알고리즘 분석',
                'description' => '홈 추천 목록을 읽어 취향 패턴을 요약합니다.',
                'href' => '/func/youtube-feed',
                'status' => 'live',
            ],
            [
                'key' => 'history',
                'label' => '분석 이력',
                'description' => '이 브라우저에서 분석한 기록을 봅니다.',
                'href' => '/func/history',
                'status' => 'live',
            ],
            [
                'key' => 'taste-lab',
                'label' => '취향 실험실',
                'description' => '여러 반응을 비교하는 실험형 인터랙션.',
                'href' => '',
                'status' => 'soon',
            ],
            [
                'key' => 'pattern-check',
                'label' => '패턴 체크',
                'description' => '반복 선택과 관심 축을 정리하는 체크 도구.',
                'href' => '',
                'status' => 'soon',
            ],
        ];
    }

    private function getFuncLayoutData(string $currentKey, bool $youtubeConfigured): array
    {
        return [
            'youtubeConfigured' => $youtubeConfigured,
            'funcCurrentKey' => $currentKey,
            'funcMenuItems' => $this->getFuncMenuItems(),
        ];
    }

    private function getFuncFeatures(): array
    {
        return [
            [
                'key'      => 'youtube-feed',
                'title'    => 'Youtube 알고리즘 분석',
                'category' => '추천 피드 기반',
                'tag'      => '북마클릿 방식',
                'summary'  => 'YouTube 홈에서 실제로 보이는 추천 영상을 가져와 성향 키워드와 관심 축을 요약합니다. 분석 결과는 엔터테인먼트 목적의 유사 분류이며 의학적 또는 심리학적 진단이 아닙니다.',
                'href'     => '/func/youtube-feed',
                'status'   => 'live',
            ],
            [
                'key'      => 'taste-lab',
                'title'    => '취향 실험실',
                'category' => '실험형 인터랙션',
                'tag'      => '',
                'summary'  => '여러 반응을 비교하는 실험형 인터랙션. 준비 중입니다.',
                'href'     => '',
                'status'   => 'soon',
            ],
        ];
    }

    public function history(): void
    {
        $voterToken = $this->ensureVoterToken();
        $rows = (new FuncAnalysis())->findByCreatorToken($voterToken);

        $items = [];
        foreach ($rows as $row) {
            $payload = json_decode((string)($row['payload'] ?? ''), true) ?: [];
            $analysis = $payload['analysis'] ?? null;
            $llmAnalysis = $payload['llmAnalysis'] ?? null;
            $resultType = $llmAnalysis['result_type'] ?? ($analysis['resultType'] ?? '—');
            $mbti = $analysis['mbti'] ?? '';
            $items[] = [
                'analysis_id' => (int)$row['analysis_id'],
                'share_token' => (string)($row['share_token'] ?? ''),
                'video_count' => (int)($row['video_count'] ?? 0),
                'result_type' => $resultType,
                'mbti' => $mbti,
                'created_at' => (string)($row['created_at'] ?? ''),
            ];
        }

        $this->renderLayout('func', 'func/history', [
            'isFuncPage' => true,
            'pageTitle' => '분석 이력',
            'additionalCss' => ['/css/func.css'],
            'historyItems' => $items,
        ] + $this->getFuncLayoutData('history', true));
    }

    public function index(): void
    {
        $youtube = YouTubeConfig::load();
        $youtubeConfigured = !empty($youtube['api_key']);

        $this->renderLayout('func', 'func/index', [
            'isFuncPage'   => true,
            'pageTitle'    => '인터랙트',
            'additionalCss' => ['/css/func.css'],
            'funcFeatures' => $this->getFuncFeatures(),
        ] + $this->getFuncLayoutData('index', $youtubeConfigured));
    }

    public function youtubeFeed(): void
    {
        $config = require __DIR__ . '/../../config/config.php';
        $appUrl = rtrim((string)($config['app_url'] ?? ''), '/');
        $youtube = YouTubeConfig::load();
        $youtubeConfigured = !empty($youtube['api_key']);

        $analyzeUrl = $appUrl . '/func/analyze';
        $bookmarkletJs = "javascript:(function(){"
            . "if(location.hostname!=='www.youtube.com'&&location.hostname!=='youtube.com'){alert('YouTube 홈에서 실행해주세요.');return;}"
            . "var TARGET=60,MAX_STEPS=12,STEP_MS=900;"
            . "var collect=function(){"
            . "return [...new Set([...document.querySelectorAll('a[href*=\"watch?v=\"]')]"
            . ".map(function(a){try{return new URL(a.href).searchParams.get('v')}catch(e){return null}})"
            . ".filter(function(v){return v&&/^[a-zA-Z0-9_-]{11}$/.test(v)}))];"
            . "};"
            . "var steps=0;"
            . "var tick=function(){"
            . "var ids=collect();"
            . "if(ids.length>=TARGET||steps>=MAX_STEPS){"
            . "var u=ids.slice(0,TARGET);"
            . "if(!u.length){alert('추천 영상을 찾지 못했습니다. YouTube 홈에서 실행해주세요.');return;}"
            . "location.href='" . $analyzeUrl . "?ids='+u.join(',');"
            . "return;"
            . "}"
            . "window.scrollTo(0,document.documentElement.scrollHeight);"
            . "steps++;"
            . "setTimeout(tick,STEP_MS);"
            . "};"
            . "tick();"
            . "})();";

        $this->renderLayout('func', 'func/youtube-feed', [
            'isFuncPage'      => true,
            'pageTitle'       => 'Youtube 알고리즘 분석',
            'additionalCss'   => ['/css/func.css'],
            'bookmarkletJs'   => $bookmarkletJs,
            'analyzeUrl'      => $analyzeUrl,
        ] + $this->getFuncLayoutData('youtube-feed', $youtubeConfigured));
    }

    public function analyze(): void
    {
        $youtube = YouTubeConfig::load();
        if (empty($youtube['api_key'])) {
            $this->renderLayout('func', 'func/analyze', [
                'isFuncPage' => true,
                'pageTitle' => '분석 결과',
                'additionalCss' => ['/css/func.css'],
                'error' => 'YouTube API 키가 설정되지 않았습니다.',
                'analysis' => null,
            ] + $this->getFuncLayoutData('youtube-feed', false));
            return;
        }

        $rawIds = trim((string)($_GET['ids'] ?? ''));
        if ($rawIds === '') {
            $this->redirect('/func');
            return;
        }

        // ID 파싱 및 검증
        $parts = explode(',', $rawIds);
        $videoIds = array_values(array_unique(array_filter(
            array_map('trim', $parts),
            static fn($id) => preg_match('/^[a-zA-Z0-9_-]{11}$/', $id) === 1
        )));
        $videoIds = array_slice($videoIds, 0, 60);

        if (empty($videoIds)) {
            $this->redirect('/func');
            return;
        }

        $ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
        $activeProvider = (string)(AiProviderConfig::load()['active_provider'] ?? 'none');
        $analysisModel = new FuncAnalysis();
        $idsHash = FuncAnalysis::hashIds($videoIds, $activeProvider);

        // DB 캐시 우선 — 같은 ids 조합이면 외부 API 호출 없이 저장된 결과 반환
        $cachedRow = $analysisModel->findByIdsHash($idsHash);
        if ($cachedRow !== null) {
            $payload = json_decode((string)$cachedRow['payload'], true) ?: [];
            $this->renderAnalysisPage(
                (int)$cachedRow['analysis_id'],
                (string)($cachedRow['share_token'] ?? ''),
                $payload['analysis'] ?? null,
                $payload['llmAnalysis'] ?? null,
                $payload['llmError'] ?? null,
                (int)$cachedRow['video_count'],
                $analysisModel
            );
            return;
        }

        $cache = Cache::getInstance();
        $tempKey = Cache::key('func_analyze_temp', $idsHash);
        // LLM 일시 오류로 DB save 못 한 직전 결과 — 5분간 외부 API 재호출 회피
        $tempPayload = $cache->get($tempKey);
        if (is_array($tempPayload)) {
            $this->renderAnalysisPage(
                0,
                '',
                $tempPayload['analysis'] ?? null,
                $tempPayload['llmAnalysis'] ?? null,
                $tempPayload['llmError'] ?? null,
                (int)($tempPayload['videoCount'] ?? 0),
                $analysisModel
            );
            return;
        }

        $rateKey = Cache::key('func_analyze_rate', $ip);
        $rateCount = (int)($cache->get($rateKey) ?? 0) + 1;
        $cache->set($rateKey, $rateCount, 60);
        if ($rateCount > 10) {
            $this->auditFuncAction('func.analyze', ['reason' => 'rate_limited', 'count' => $rateCount, 'video_count' => count($videoIds)], 'denied');
            $this->renderLayout('func', 'func/analyze', [
                'isFuncPage' => true,
                'pageTitle' => '분석 결과',
                'additionalCss' => ['/css/func.css'],
                'error' => '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.',
                'analysis' => null,
            ] + $this->getFuncLayoutData('youtube-feed', true));
            return;
        }

        try {
            $feedService = new YouTubeFeedService();
            $videos = $feedService->fetchVideoSnippetsPublic($videoIds, (string)$youtube['api_key']);
        } catch (\Throwable $e) {
            $this->auditFuncAction('func.analyze', ['reason' => 'youtube_api_failed', 'video_count' => count($videoIds), 'error' => $e->getMessage()], 'error');
            $this->renderLayout('func', 'func/analyze', [
                'isFuncPage' => true,
                'pageTitle' => '분석 결과',
                'additionalCss' => ['/css/func.css'],
                'error' => 'YouTube API 호출에 실패했습니다: ' . $e->getMessage(),
                'analysis' => null,
            ] + $this->getFuncLayoutData('youtube-feed', true));
            return;
        }

        $analysis = $this->analyzeVideoFeed($videos);

        $llmAnalysis = null;
        $llmError = null;
        if ($activeProvider !== 'none') {
            try {
                switch ($activeProvider) {
                    case 'gemini':
                        $llmAnalysis = (new GeminiAnalysisService())->analyze($videos, GeminiConfig::load());
                        break;
                    case 'openai':
                        $llmAnalysis = (new OpenAiAnalysisService())->analyze($videos, OpenAiConfig::load());
                        break;
                }
                if ($llmAnalysis === null) {
                    $llmError = 'LLM 분석을 일시적으로 사용할 수 없습니다. 키워드 기반 분석 결과만 표시됩니다.';
                }
            } catch (\Throwable $e) {
                $llmAnalysis = null;
                $llmError = 'LLM 분석을 일시적으로 사용할 수 없습니다. 키워드 기반 분석 결과만 표시됩니다.';
            }
        }

        $videoCount = count($videos);
        $analysisId = 0;
        $shareToken = '';
        if ($llmError === null) {
            $voterToken = $this->ensureVoterToken();
            $saved = $analysisModel->save($idsHash, $videoIds, $activeProvider, [
                'analysis' => $analysis,
                'llmAnalysis' => $llmAnalysis,
                'llmError' => null,
                'videoCount' => $videoCount,
            ], $ip, $voterToken);
            $analysisId = $saved['id'];
            $shareToken = $saved['token'];
            $this->auditFuncAction('func.analyze', [
                'analysis_id' => $analysisId,
                'provider' => $activeProvider,
                'video_count' => $videoCount,
                'llm' => $llmAnalysis !== null,
            ], 'success');
        } else {
            // 영구 저장은 안 하지만 5분간 같은 ids 새로고침은 외부 API skip
            $cache->set($tempKey, [
                'analysis' => $analysis,
                'llmAnalysis' => null,
                'llmError' => $llmError,
                'videoCount' => $videoCount,
            ], 300);
            $this->auditFuncAction('func.analyze', [
                'provider' => $activeProvider,
                'video_count' => $videoCount,
                'reason' => 'llm_failed_temp_cached',
            ], 'error');
        }

        $this->renderAnalysisPage($analysisId, $shareToken, $analysis, $llmAnalysis, $llmError, $videoCount, $analysisModel);
    }

    private function renderAnalysisPage(int $analysisId, string $shareToken, ?array $analysis, ?array $llmAnalysis, ?string $llmError, int $videoCount, FuncAnalysis $analysisModel): void
    {
        $userVote = null;
        if ($analysisId > 0) {
            $voterToken = $this->ensureVoterToken();
            $userVote = $analysisModel->getUserVote($analysisId, $voterToken);
        }

        $this->renderLayout('func', 'func/analyze', [
            'isFuncPage' => true,
            'pageTitle' => '분석 결과',
            'additionalCss' => ['/css/func.css'],
            'error' => null,
            'analysis' => $analysis,
            'llmAnalysis' => $llmAnalysis,
            'llmError' => $llmError,
            'videoCount' => $videoCount,
            'analysisId' => $analysisId,
            'shareToken' => $shareToken,
            'userVote' => $userVote,
            'csrfToken' => $this->view->csrfToken(),
        ] + $this->getFuncLayoutData('youtube-feed', true));
    }

    private function ensureVoterToken(): string
    {
        $existing = $_COOKIE['func_voter'] ?? '';
        if (is_string($existing) && preg_match('/^[a-f0-9]{40}$/', $existing) === 1) {
            return $existing;
        }
        $token = bin2hex(random_bytes(20));
        $_COOKIE['func_voter'] = $token;
        if (!headers_sent()) {
            setcookie('func_voter', $token, [
                'expires' => time() + 86400 * 365,
                'path' => '/',
                'secure' => !empty($_SERVER['HTTPS']),
                'httponly' => true,
                'samesite' => 'Lax',
            ]);
        }
        return $token;
    }

    public function analyzeShort(string $token): void
    {
        // 16자 hex 토큰만 허용 — 옛 정수형 /a/<id> 링크는 여기서 차단되어 /func로
        if (preg_match('/^[a-f0-9]{16}$/', $token) !== 1) {
            $this->redirect('/func');
            return;
        }
        $row = (new FuncAnalysis())->findByShareToken($token);
        if ($row === null || empty($row['ids_csv'])) {
            $this->redirect('/func');
            return;
        }
        $this->redirect('/func/analyze?ids=' . rawurlencode((string)$row['ids_csv']));
    }

    public function reactAnalysis(): void
    {
        header('Content-Type: application/json; charset=utf-8');

        if (!$this->validateCsrfToken()) {
            $this->auditFuncAction('func.react', ['reason' => 'csrf_invalid'], 'denied');
            http_response_code(403);
            echo json_encode(['ok' => false, 'error' => 'csrf_invalid']);
            return;
        }

        $analysisId = (int)($_POST['analysis_id'] ?? 0);
        $vote = (string)($_POST['vote'] ?? '');
        if ($analysisId <= 0 || ($vote !== 'like' && $vote !== 'dislike')) {
            $this->auditFuncAction('func.react', ['reason' => 'invalid_request', 'analysis_id' => $analysisId, 'vote' => $vote], 'rejected');
            http_response_code(400);
            echo json_encode(['ok' => false, 'error' => 'invalid_request']);
            return;
        }

        $exists = Database::getInstance()->fetch(
            'SELECT analysis_id FROM func_analysis_list WHERE analysis_id = ?',
            [$analysisId]
        );
        if ($exists === null) {
            $this->auditFuncAction('func.react', ['reason' => 'not_found', 'analysis_id' => $analysisId], 'rejected');
            http_response_code(404);
            echo json_encode(['ok' => false, 'error' => 'not_found']);
            return;
        }

        $model = new FuncAnalysis();

        $ip = $_SERVER['REMOTE_ADDR'] ?? null;
        $cache = Cache::getInstance();
        $rateKey = Cache::key('func_react_rate', $ip ?? 'unknown');
        $rateCount = (int)($cache->get($rateKey) ?? 0) + 1;
        $cache->set($rateKey, $rateCount, 60);
        if ($rateCount > 30) {
            $this->auditFuncAction('func.react', ['reason' => 'rate_limited', 'analysis_id' => $analysisId, 'count' => $rateCount], 'denied');
            http_response_code(429);
            echo json_encode(['ok' => false, 'error' => 'rate_limited']);
            return;
        }

        $voterToken = $this->ensureVoterToken();
        $action = $model->toggleReaction($analysisId, $voterToken, $vote, $ip);
        $userVote = $model->getUserVote($analysisId, $voterToken);

        $this->auditFuncAction('func.react', [
            'analysis_id' => $analysisId,
            'vote' => $vote,
            'action' => $action,
        ], 'success');

        echo json_encode([
            'ok' => true,
            'action' => $action,
            'user_vote' => $userVote,
        ]);
    }

    private function auditFuncAction(string $action, array $details = [], string $result = 'success'): void
    {
        // 익명 공개 엔드포인트 — actor 식별자는 IP만 의미 있음
        $logPayload = [
            'action' => $action,
            'result' => $result,
            'ip' => $this->getClientIp(),
            'method' => $this->getRequestMethod(),
            'uri' => $_SERVER['REQUEST_URI'] ?? '',
            'details' => $details,
        ];

        $message = json_encode($logPayload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($message === false) {
            $message = sprintf('action=%s result=%s details=encode_failed', $action, $result);
        }

        if ($result === 'error') {
            Logger::error('func_audit', $message);
            return;
        }
        if ($result === 'rejected' || $result === 'denied') {
            Logger::warn('func_audit', $message);
            return;
        }
        Logger::info('func_audit', $message);
    }

    private function getClientIp(): string
    {
        $keys = ['HTTP_X_FORWARDED_FOR', 'HTTP_CLIENT_IP', 'REMOTE_ADDR'];

        foreach ($keys as $key) {
            if (!isset($_SERVER[$key])) {
                continue;
            }

            $raw = trim((string)$_SERVER[$key]);
            if ($raw === '') {
                continue;
            }

            if ($key === 'HTTP_X_FORWARDED_FOR') {
                $parts = explode(',', $raw);
                $candidate = trim((string)$parts[0]);
                return mb_substr($candidate, 0, 100, 'UTF-8');
            }

            return mb_substr($raw, 0, 100, 'UTF-8');
        }

        return '';
    }

    private function analyzeVideoFeed(array $videos): array
    {
        $keywordMap = [
            '분석형' => ['경제', '투자', '코딩', '개발', '과학', '뉴스', '다큐', '전략', 'finance', 'coding', 'analysis', 'documentary'],
            '탐험형' => ['여행', '브이로그', '모험', '캠핑', '먹방', 'trip', 'travel', 'vlog', 'food'],
            '몰입형' => ['음악', '공부', '집중', '명상', '로파이', 'music', 'study', 'focus', 'lofi'],
            '사교형' => ['토크', '예능', '인터뷰', '라이브', '쇼츠', 'talk', 'interview', 'live', 'shorts'],
        ];

        $scores = [
            '분석형' => 0,
            '탐험형' => 0,
            '몰입형' => 0,
            '사교형' => 0,
        ];

        foreach ($videos as $video) {
            $haystack = trim(implode(' ', [
                (string)($video['title'] ?? ''),
                (string)($video['description'] ?? ''),
                (string)($video['channel_title'] ?? ''),
                implode(' ', (array)($video['tags'] ?? [])),
            ]));
            $haystack = mb_strtolower($haystack, 'UTF-8');

            foreach ($keywordMap as $type => $keywords) {
                foreach ($keywords as $keyword) {
                    $scores[$type] += substr_count($haystack, mb_strtolower($keyword, 'UTF-8'));
                }
            }
        }

        arsort($scores);
        $topType = (string)array_key_first($scores);
        $topScore = (int)($scores[$topType] ?? 0);

        $secondaryType = '';
        foreach (array_keys($scores) as $type) {
            if ($type !== $topType) {
                $secondaryType = $type;
                break;
            }
        }

        $summary = $topScore > 0
            ? 'YouTube 피드 기준으로 ' . $topType . ' 성향이 두드러지며 ' . $secondaryType . ' 성향이 보조적으로 관찰됩니다.'
            : '조회된 영상의 키워드 밀도가 낮아 기본 성향(탐험형)으로 분석되었습니다.';

        $total = array_sum($scores);
        $percentages = [];
        foreach ($scores as $type => $score) {
            $percentages[$type] = $total > 0 ? (int)round(($score / $total) * 100) : 0;
        }

        $mbtiAxes = $this->buildMbtiAxes($scores);

        return [
            'resultType' => $topScore > 0 ? $topType : '탐험형',
            'summary' => $summary,
            'scores' => $scores,
            'percentages' => $percentages,
            'mbti' => $mbtiAxes['code'],
            'mbtiAxes' => $mbtiAxes['axes'],
        ];
    }

    private function buildMbtiAxes(array $scores): array
    {
        $a = (int)($scores['분석형'] ?? 0);
        $e = (int)($scores['탐험형'] ?? 0);
        $m = (int)($scores['몰입형'] ?? 0);
        $s = (int)($scores['사교형'] ?? 0);

        $pair = static function (int $left, int $right): int {
            $sum = $left + $right;
            return $sum > 0 ? (int)round(($left / $sum) * 100) : 50;
        };

        // 사교형(E) vs 몰입형(I)
        $ePct = $pair($s, $m);
        // 탐험형(N) vs 분석형(S)
        $nPct = $pair($e, $a);
        // 분석형(T) vs 사교형(F)
        $tPct = $pair($a, $s);
        // 몰입형(J) vs 탐험형(P)
        $jPct = $pair($m, $e);

        $axes = [
            ['left' => 'E', 'right' => 'I', 'leftPct' => $ePct, 'rightPct' => 100 - $ePct],
            ['left' => 'N', 'right' => 'S', 'leftPct' => $nPct, 'rightPct' => 100 - $nPct],
            ['left' => 'F', 'right' => 'T', 'leftPct' => 100 - $tPct, 'rightPct' => $tPct],
            ['left' => 'P', 'right' => 'J', 'leftPct' => 100 - $jPct, 'rightPct' => $jPct],
        ];

        $code = '';
        foreach ($axes as $ax) {
            $code .= $ax['leftPct'] >= 50 ? $ax['left'] : $ax['right'];
        }

        return ['code' => $code, 'axes' => $axes];
    }
}
