<?php

namespace Blog\Services;

class YouTubeFeedService
{
    private const API_BASE = 'https://www.googleapis.com/youtube/v3';

    public function fetchVideoSnippetsPublic(array $videoIds, string $apiKey): array
    {
        return $this->fetchVideoSnippets($videoIds, $apiKey);
    }

    private function fetchVideoSnippets(array $videoIds, string $apiKey): array
    {
        $chunks = array_chunk($videoIds, 50);
        $result = [];

        foreach ($chunks as $chunk) {
            $data = $this->request('/videos', [
                'part' => 'snippet,topicDetails',
                'id' => implode(',', $chunk),
                'maxResults' => count($chunk),
                'key' => $apiKey,
            ]);

            foreach (($data['items'] ?? []) as $item) {
                $snippet = $item['snippet'] ?? [];
                $result[] = [
                    'video_id' => (string)($item['id'] ?? ''),
                    'title' => (string)($snippet['title'] ?? ''),
                    'description' => (string)($snippet['description'] ?? ''),
                    'channel_title' => (string)($snippet['channelTitle'] ?? ''),
                    'tags' => array_values(array_filter(array_map('strval', (array)($snippet['tags'] ?? [])))),
                    'category_id' => (string)($snippet['categoryId'] ?? ''),
                ];
            }
        }

        return $result;
    }

    private function request(string $path, array $query): array
    {
        $url = self::API_BASE . $path . '?' . http_build_query($query);

        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_CONNECTTIMEOUT => 8,
                CURLOPT_TIMEOUT => 15,
                CURLOPT_HTTPHEADER => ['Accept: application/json'],
            ]);
            $body = curl_exec($ch);
            $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);

            if (!is_string($body) || $body === '') {
                throw new \RuntimeException('youtube api request failed');
            }

            $decoded = json_decode($body, true);
            if (!is_array($decoded)) {
                throw new \RuntimeException('youtube api response decode failed');
            }

            if ($status >= 400 || isset($decoded['error'])) {
                $message = (string)($decoded['error']['message'] ?? 'youtube api error');
                throw new \RuntimeException($message);
            }

            return $decoded;
        }

        $context = stream_context_create([
            'http' => [
                'method' => 'GET',
                'timeout' => 15,
                'header' => "Accept: application/json\r\n",
            ],
        ]);

        $body = @file_get_contents($url, false, $context);
        if (!is_string($body) || $body === '') {
            throw new \RuntimeException('youtube api request failed');
        }

        $decoded = json_decode($body, true);
        if (!is_array($decoded)) {
            throw new \RuntimeException('youtube api response decode failed');
        }

        if (isset($decoded['error'])) {
            $message = (string)($decoded['error']['message'] ?? 'youtube api error');
            throw new \RuntimeException($message);
        }

        return $decoded;
    }
}
