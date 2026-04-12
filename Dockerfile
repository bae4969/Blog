FROM php:8.2-apache

ARG USERNAME=devuser
ARG USER_UID=1000
ARG USER_GID=3000
ARG APP_ENV=prod
ENV APP_ENV=${APP_ENV}

# 0. 유저 생성
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m -s /bin/bash $USERNAME

# 1. 필수 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng-dev \
    libjpeg-dev \
    libfreetype6-dev \
    libonig-dev \
    libxml2-dev \
    zip \
    unzip \
    git \
    curl \
    nodejs \
    npm \
    $PHPIZE_DEPS \
    && npx -y playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# 2. PHP 확장 모듈 설치 (DB 및 이미지 처리)
RUN docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j$(nproc) \
    mysqli \
    pdo_mysql \
    mbstring \
    exif \
    bcmath \
    sockets \
    gd \
    opcache

# 2-1. Xdebug 설치
RUN pecl install xdebug \
    && docker-php-ext-enable xdebug

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

# 9. PHP 설정
RUN echo "memory_limit = 512M" > /usr/local/etc/php/conf.d/memory.ini \
    && echo "upload_max_filesize = 10M\npost_max_size = 20M" > /usr/local/etc/php/conf.d/uploads.ini

# 10. Apache/PHP 상태 확인
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
        CMD curl -fsS http://localhost/ || exit 1

# 11. 유저 설정
USER $USERNAME
