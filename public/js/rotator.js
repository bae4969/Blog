/*
  회전 카드 — 768px 이하에서 목록을 한 장씩 보여주고 자동으로 넘긴다.
  (`/stocks` 의 지수·환율 카드와 거래대금·포트폴리오 TOP10)

  마크업은 템플릿이 갖는다(stocks_index.html):
    [data-rotator]              섹션. data-rotator-item(슬라이드 선택자) ·
                                data-rotator-interval · data-rotator-delay (ms)
      .rotator-count            "n / N"
      [data-rotator-expand]     (있으면) 지금의 목록으로 펼치기
      [data-rotator-track]      슬라이드의 부모 — 768px 이하에서 가로 스냅 스크롤(stocks.css)
      .rotator-bar > i          다음 장까지 남은 시간

  - 넘기는 동작 자체는 브라우저의 스냅 스크롤이다. 손가락 스와이프를 따로 구현하지 않는다.
  - 목록을 그리는 JS(quotes.js·stocks_dashboard.js)는 이 모듈을 모른다. 트랙의 자식이
    바뀌면(시장 전환·다시 받기) 첫 장으로 돌아간다.
  - 자동 넘김을 멈추는 때: 손을 댄 뒤 6초 · 화면 밖 · 탭 숨김 · 펼침 · 동작 줄이기 설정 ·
    768px 초과.
*/
(function () {
    'use strict';

    var MOBILE = window.matchMedia('(max-width: 768px)');
    var REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)');
    var HOLD_MS = 6000;
    var rotators = [];

    function Rotator(root) {
        this.root = root;
        this.track = root.querySelector('[data-rotator-track]');
        this.countEl = root.querySelector('.rotator-count');
        this.bar = root.querySelector('.rotator-bar');
        this.expandBtn = root.querySelector('[data-rotator-expand]');
        this.itemSel = root.dataset.rotatorItem || '*';
        this.interval = Number(root.dataset.rotatorInterval) || 4000;
        this.delay = Number(root.dataset.rotatorDelay) || 0;
        this.index = 0;
        this.timer = null;
        this.visible = true;
        this.expanded = false;
        this.bind();
        this.go(0, false);
        this.restart();
    }

    Rotator.prototype.slides = function () {
        var out = [];
        for (var i = 0; i < this.track.children.length; i++) {
            if (this.track.children[i].matches(this.itemSel)) out.push(this.track.children[i]);
        }
        return out;
    };

    Rotator.prototype.active = function () {
        return MOBILE.matches && !this.expanded;
    };

    Rotator.prototype.canAuto = function () {
        return this.active() && !REDUCED.matches && this.visible && !document.hidden &&
            this.slides().length > 1;
    };

    Rotator.prototype.sync = function () {
        var n = this.slides().length;
        if (this.countEl) this.countEl.textContent = n > 1 ? (this.index + 1) + ' / ' + n : '';
        this.root.classList.toggle('rotator-single', n < 2);
    };

    Rotator.prototype.go = function (i, smooth) {
        var n = this.slides().length;
        this.index = n ? ((i % n) + n) % n : 0;
        if (this.active()) {
            this.track.scrollTo({
                left: this.index * this.track.clientWidth,
                behavior: smooth ? 'smooth' : 'auto'
            });
        }
        this.sync();
    };

    Rotator.prototype.stop = function () {
        clearTimeout(this.timer);
        this.timer = null;
        this.root.classList.remove('rotator-running');
    };

    /** ms 뒤에 다음 장으로. 진행바도 같은 시간으로 처음부터 다시 채운다. */
    Rotator.prototype.schedule = function (ms) {
        var self = this;
        this.stop();
        if (!this.canAuto()) return;
        if (this.bar) {
            this.bar.style.setProperty('--rotator-dur', ms + 'ms');
            var fresh = document.createElement('i');
            if (this.bar.firstElementChild) this.bar.replaceChild(fresh, this.bar.firstElementChild);
            else this.bar.appendChild(fresh);
        }
        this.root.classList.add('rotator-running');
        this.timer = setTimeout(function () {
            var n = self.slides().length;
            // 마지막 장 → 첫 장은 되감는 애니메이션 없이 바로 넘긴다.
            self.go(self.index + 1, self.index + 1 < n);
            self.schedule(self.interval);
        }, ms);
    };

    /** 처음부터 다시 잰다. 지연(delay)을 다시 얹어 나란히 선 카드끼리 박자가 어긋난 채로 남게 한다. */
    Rotator.prototype.restart = function () {
        this.schedule(this.interval + this.delay);
    };

    Rotator.prototype.setExpanded = function (on) {
        this.expanded = on;
        this.root.classList.toggle('rotator-expanded', on);
        if (this.expandBtn) {
            // ⚠️ `textContent` 를 버튼에 직접 쓰면 **안에 있는 SVG 아이콘까지 지운다**
            //    (프로젝트 규칙상 버튼에는 아이콘이 있다). 라벨 span 만 바꾼다.
            var lab = this.expandBtn.querySelector('[data-rotator-expand-label]');
            (lab || this.expandBtn).textContent = on ? '접기' : '전체';
            this.expandBtn.setAttribute('aria-expanded', on ? 'true' : 'false');
        }
        if (on) {
            this.stop();
        } else {
            this.go(this.index, false);
            this.restart();
        }
    };

    Rotator.prototype.bind = function () {
        var self = this;
        var settle = null;

        // 손가락으로 넘긴 경우 — 스크롤이 멈춘 자리에서 번호를 맞추고 손 뗀 뒤부터 다시 잰다.
        this.track.addEventListener('scroll', function () {
            if (!self.active()) return;
            clearTimeout(settle);
            settle = setTimeout(function () {
                var i = Math.round(self.track.scrollLeft / Math.max(1, self.track.clientWidth));
                if (i === self.index) return;
                self.index = i;
                self.sync();
                self.schedule(HOLD_MS);
            }, 120);
        }, { passive: true });

        function hold() { self.stop(); }
        function release() { self.schedule(HOLD_MS); }
        // 스크롤이 시작되면 브라우저가 pointercancel 을 보낸다 — 손을 뗀 것과 같이 다룬다.
        this.track.addEventListener('pointerdown', hold, { passive: true });
        this.track.addEventListener('pointerup', release, { passive: true });
        this.track.addEventListener('pointercancel', release, { passive: true });
        this.root.addEventListener('focusin', hold);
        this.root.addEventListener('focusout', release);

        if (this.expandBtn) {
            this.expandBtn.addEventListener('click', function (event) {
                event.preventDefault();
                self.setExpanded(!self.expanded);
            });
        }

        new MutationObserver(function () {
            if (self.expanded && self.slides().length < 2) self.setExpanded(false);
            self.go(0, false);
            self.restart();
        }).observe(this.track, { childList: true });

        if ('IntersectionObserver' in window) {
            new IntersectionObserver(function (entries) {
                var visible = entries[entries.length - 1].isIntersecting;
                if (visible === self.visible) return;
                self.visible = visible;
                if (visible) self.restart();
                else self.stop();
            }).observe(this.root);
        }
    };

    function each(fn) {
        for (var i = 0; i < rotators.length; i++) fn(rotators[i]);
    }

    function onModeChange() {
        each(function (r) {
            r.go(0, false);
            r.restart();
        });
    }

    function listen(mq, fn) {
        if (mq.addEventListener) mq.addEventListener('change', fn);
        else if (mq.addListener) mq.addListener(fn);   // Safari 13 이하
    }

    function init() {
        var roots = document.querySelectorAll('[data-rotator]');
        for (var i = 0; i < roots.length; i++) {
            if (roots[i].querySelector('[data-rotator-track]')) rotators.push(new Rotator(roots[i]));
        }
        if (!rotators.length) return;

        document.addEventListener('visibilitychange', function () {
            each(function (r) {
                if (document.hidden) r.stop();
                else r.restart();
            });
        });
        listen(MOBILE, onModeChange);
        listen(REDUCED, onModeChange);

        // 폭이 바뀌면(가로 회전 등) 한 장 폭도 바뀐다 — 보던 장에 다시 맞춘다.
        var resizeTimer = null;
        window.addEventListener('resize', function () {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                each(function (r) { r.go(r.index, false); });
            }, 150);
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
