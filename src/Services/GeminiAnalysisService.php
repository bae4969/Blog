<?php

namespace Blog\Services;

class GeminiAnalysisService
{
    private const ENDPOINT_BASE = 'https://generativelanguage.googleapis.com/v1beta/models/';
    private const MODELS_LIST_ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models';

    public function listModels(string $apiKey, int $timeout = 15): ?array
    {
        if ($apiKey === '') {
            return null;
        }

        $ch = curl_init(self::MODELS_LIST_ENDPOINT);
        if ($ch === false) {
            return null;
        }
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => ['x-goog-api-key: ' . $apiKey],
            CURLOPT_TIMEOUT => $timeout,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_FOLLOWLOCATION => false,
        ]);
        $response = curl_exec($ch);
        $httpCode = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        if ($response === false || $httpCode !== 200 || !is_string($response)) {
            return null;
        }

        $decoded = json_decode($response, true);
        if (!is_array($decoded) || !isset($decoded['models']) || !is_array($decoded['models'])) {
            return null;
        }

        $models = [];
        foreach ($decoded['models'] as $entry) {
            if (!is_array($entry)) {
                continue;
            }
            $name = (string)($entry['name'] ?? '');
            if ($name === '') {
                continue;
            }
            $methods = (array)($entry['supportedGenerationMethods'] ?? []);
            if (!in_array('generateContent', $methods, true)) {
                continue;
            }
            $id = preg_replace('~^models/~', '', $name);
            if ($id !== '' && $id !== null) {
                $models[] = $id;
            }
        }

        $models = array_values(array_unique($models));
        sort($models);
        return $models;
    }

    public function analyze(array $videos, array $config): ?array
    {
        $apiKey = trim((string)($config['api_key'] ?? ''));
        $model = trim((string)($config['model'] ?? ''));
        $timeout = (int)($config['timeout_sec'] ?? 30);

        if ($apiKey === '' || $model === '' || empty($videos)) {
            return null;
        }

        $prompt = $this->buildPrompt($videos);
        $body = json_encode([
            'contents' => [
                ['parts' => [['text' => $prompt]]],
            ],
            'generationConfig' => [
                'temperature' => 0.2,
                'responseMimeType' => 'application/json',
            ],
        ], JSON_UNESCAPED_UNICODE);

        if ($body === false) {
            return null;
        }

        $url = self::ENDPOINT_BASE . rawurlencode($model) . ':generateContent';
        $response = $this->postJson($url, $body, $apiKey, $timeout);
        if ($response === null) {
            return null;
        }

        return $this->parseResponse($response);
    }

    private function buildPrompt(array $videos): string
    {
        $lines = [];
        $idx = 1;
        foreach ($videos as $v) {
            $title = trim((string)($v['title'] ?? ''));
            $channel = trim((string)($v['channel_title'] ?? ''));
            if ($title === '') {
                continue;
            }
            $lines[] = $idx . '. ' . $title . ' — ' . $channel;
            $idx++;
        }
        $list = implode("\n", $lines);

        return "당신은 YouTube 추천 피드를 분석하는 큐레이터입니다.\n\n"
            . "아래 영상 목록(제목 — 채널명)의 메타데이터만으로 사용자의 시청 성향을 분석하세요.\n\n"
            . "## 입력\n" . $list . "\n\n"
            . "## 출력 규칙\n"
            . "- 메타데이터에서 직접 보이는 패턴만 사용. 추측·환각 금지. 보이지 않는 것은 출력하지 마세요.\n"
            . "- 톤은 따뜻하고 긍정적으로. 팩트는 정확히 짚되 사용자가 자기 취향을 흥미롭게 받아들일 수 있게 표현하세요. 수치심·비난·단정적 부정 어휘는 피하세요.\n"
            . "- 다음 JSON 스키마로만 출력하세요. 코드펜스(```)·주석·여분 텍스트 없이 순수 JSON만:\n\n"
            . "{\n"
            . "  \"result_type\": \"한 문장 라벨 (예: '느린 호흡의 단독 콘텐츠 선호자')\",\n"
            . "  \"summary\": \"2-3문장 한국어 요약, 사용자의 취향이 어떤 매력으로 비추어지는지 따뜻하게\",\n"
            . "  \"traits\": [\"특성1\", \"특성2\", \"특성3\"],\n"
            . "  \"hidden_axes\": [\"겉으로는 다르지만 공통된 축이 있다면 1-2개. 없으면 빈 배열\"],\n"
            . "  \"honest_critique\": \"이 피드의 편향이나 아쉬운 점이 있다면, 사실은 짚되 부드럽고 격려하는 한 줄. 새로 탐색해볼 만한 결을 살짝 권하는 톤도 좋음.\",\n"
            . "  \"top_signals\": [{\"keyword\": \"...\", \"frequency\": 5, \"channels\": [\"...\"]}],\n"
            . "  \"confidence\": 0.0\n"
            . "}\n\n"
            . "confidence는 메타데이터 양·품질에 비춘 자체 신뢰도(0.0~1.0).";
    }

    private function postJson(string $url, string $body, string $apiKey, int $timeout): ?string
    {
        $ch = curl_init($url);
        if ($ch === false) {
            return null;
        }

        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $body,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'x-goog-api-key: ' . $apiKey,
            ],
            CURLOPT_TIMEOUT => $timeout,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_FOLLOWLOCATION => false,
        ]);

        $response = curl_exec($ch);
        $httpCode = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);

        if ($response === false || $httpCode !== 200 || !is_string($response)) {
            return null;
        }

        return $response;
    }

    private function parseResponse(string $rawJson): ?array
    {
        $env = json_decode($rawJson, true);
        if (!is_array($env) || isset($env['error'])) {
            return null;
        }

        $candidates = $env['candidates'] ?? null;
        if (!is_array($candidates) || empty($candidates)) {
            return null;
        }

        $parts = $candidates[0]['content']['parts'] ?? null;
        if (!is_array($parts) || empty($parts)) {
            return null;
        }

        $inner = (string)($parts[0]['text'] ?? '');
        if ($inner === '') {
            return null;
        }

        $cleaned = (string)preg_replace('/^\s*```(?:json)?\s*/i', '', $inner);
        $cleaned = (string)preg_replace('/\s*```\s*$/', '', $cleaned);
        $cleaned = trim($cleaned);

        $data = json_decode($cleaned, true);
        if (!is_array($data)) {
            return null;
        }

        $resultType = trim((string)($data['result_type'] ?? ''));
        $summary = trim((string)($data['summary'] ?? ''));
        if ($resultType === '' || $summary === '') {
            return null;
        }

        return [
            'result_type' => $resultType,
            'summary' => $summary,
            'traits' => self::normalizeStringList((array)($data['traits'] ?? [])),
            'hidden_axes' => self::normalizeStringList((array)($data['hidden_axes'] ?? [])),
            'honest_critique' => trim((string)($data['honest_critique'] ?? '')),
            'top_signals' => $this->normalizeSignals((array)($data['top_signals'] ?? [])),
            'confidence' => max(0.0, min(1.0, (float)($data['confidence'] ?? 0.0))),
        ];
    }

    private static function normalizeStringList(array $raw): array
    {
        $out = [];
        foreach ($raw as $item) {
            $s = trim((string)$item);
            if ($s !== '') {
                $out[] = $s;
            }
            if (count($out) >= 10) {
                break;
            }
        }
        return $out;
    }

    private function normalizeSignals(array $raw): array
    {
        $out = [];
        foreach ($raw as $sig) {
            if (!is_array($sig)) {
                continue;
            }
            $kw = trim((string)($sig['keyword'] ?? ''));
            if ($kw === '') {
                continue;
            }
            $freq = max(0, (int)($sig['frequency'] ?? 0));
            $channels = self::normalizeStringList((array)($sig['channels'] ?? []));
            $out[] = [
                'keyword' => $kw,
                'frequency' => $freq,
                'channels' => array_slice($channels, 0, 5),
            ];
            if (count($out) >= 10) {
                break;
            }
        }
        return $out;
    }
}
