FROM php:8.2-apache

ARG APP_ENV=prod
ENV APP_ENV=${APP_ENV}

# 1. 필수 패키지 설치 (git, unzip은 composer 사용에 필수)
RUN apt-get update && apt-get install -y \
    libpng-dev \
    libjpeg-dev \
    libfreetype6-dev \
    libonig-dev \
    libxml2-dev \
    zip \
    unzip \
    git \
    curl \
    --no-install-recommends \
    && if [ "$APP_ENV" = "dev" ]; then apt-get install -y --no-install-recommends $PHPIZE_DEPS; fi \
    && rm -rf /var/lib/apt/lists/*

# 2. PHP 확장 모듈 설치 (DB 및 이미지 처리)
RUN docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j$(nproc) \
    mysqli \
    pdo_mysql \
    mbstring \
    exif \
    bcmath \
    gd \
    opcache

# 2-1. 개발 환경에서만 Xdebug 설치
RUN if [ "$APP_ENV" = "dev" ]; then \
            pecl install xdebug \
            && docker-php-ext-enable xdebug \
            && apt-get purge -y --auto-remove $PHPIZE_DEPS; \
        fi

# 3. Apache 설정: DocumentRoot를 /public으로 변경
ENV APACHE_DOCUMENT_ROOT=/var/www/html/public
RUN sed -ri -e 's!/var/www/html!${APACHE_DOCUMENT_ROOT}!g' /etc/apache2/sites-available/*.conf
RUN sed -ri -e 's!/var/www/html!${APACHE_DOCUMENT_ROOT}!g' /etc/apache2/apache2.conf /etc/apache2/conf-available/*.conf

# 4. Apache 모듈 활성화 (Rewrite 필수)
RUN a2enmod rewrite headers remoteip

# 5. ServerName 경고 방지
RUN echo "ServerName localhost" >> /etc/apache2/apache2.conf

# 6. Composer 설치 (컨테이너 안에서 패키지 설치를 위해)
COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

WORKDIR /var/www/html

# 7. Composer 의존성 설치 레이어 (빌드 캐시 최적화)
COPY composer.json composer.lock* ./
RUN if [ "$APP_ENV" = "prod" ]; then \
            composer install --no-dev --prefer-dist --no-interaction --no-progress --optimize-autoloader; \
        else \
            composer install --prefer-dist --no-interaction --no-progress; \
        fi

# 8. 애플리케이션 소스 복사
COPY . .

# 9. Apache/PHP 상태 확인
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
        CMD curl -fsS http://localhost/ || exit 1
