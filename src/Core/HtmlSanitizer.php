<?php

namespace Blog\Core;

use HTMLPurifier;
use HTMLPurifier_Config;

class HtmlSanitizer
{
    private static $purifier = null;

    private static function getPurifier(): HTMLPurifier
    {
        if (self::$purifier === null) {
            $config = HTMLPurifier_Config::createDefault();

            // 기본 허용 태그/속성 설정 (필요시 조정)
            $config->set('HTML.Doctype', 'HTML5');
            $config->set('Core.Encoding', 'UTF-8');
            $config->set('HTML.Allowed',
                'p,br,strong,b,em,i,u,span[style],a[href|title|target],ul,ol,li,blockquote,pre,code,' .
                'h1,h2,h3,h4,h5,h6,img[src|alt|title|width|height],hr'
            );
            $config->set('Attr.AllowedFrameTargets', ['_blank', '_self']);
            $config->set('HTML.SafeIframe', true);
            $config->set('URI.SafeIframeRegexp', '%^(https?:)?//(www.youtube.com/embed/|player.vimeo.com/video/)%.%');

            // XSS 방어 강화를 위한 추가 옵션
            $config->set('HTML.SafeEmbed', true);
            $config->set('HTML.SafeObject', true);
            $config->set('Output.FlashCompat', true);

            self::$purifier = new HTMLPurifier($config);
        }

        return self::$purifier;
    }

    public static function sanitize(string $html): string
    {
        return self::getPurifier()->purify($html);
    }
}
