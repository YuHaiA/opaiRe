const { createApp } = Vue;

createApp({
    data() {
        return {
            appVersion: 'v10.1.17',
            versionPageUrl: 'https://github.com/YuHaiA/opaiRe/releases/latest',
            isLoggedIn: !!localStorage.getItem('auth_token'),
            loginPassword: '',
            currentTab: window.location.hash.replace('#', '') || 'console',
            proxySubTab: 'general',
			showAccountsPlaintext: false,
            isRunning: false,
            tabs: [
                { id: 'console', name: '运行主页', icon: '💻' },
                { id: 'cluster', name: '集群总控', icon: '🖥️' },
                { id: 'email', name: '邮箱配置', icon: '📧' },
                { id: 'accounts', name: '账号库存', icon: '📦' },
                { id: 'cloud', name: '云端库存', icon: '☁️' },
                { id: 'sms', name: '手机接码', icon: '📱' },
				// { id: 'cf_routes', name: 'CF 路由', icon: '🌍' },
                { id: 'proxy', name: '网络代理', icon: '🌐' },
                { id: 'relay', name: '中转管仓', icon: '☁️' },
                { id: 'notify', name: '消息通知', icon: '📢' },
                { id: 'update', name: '更新中心', icon: '🧩' },
                { id: 'concurrency', name: '并发与系统', icon: '⚙️' }
            ],
            proxySubTabs: [
                { id: 'general', name: '通用', icon: '🧭' },
                { id: 'clash', name: 'Clash', icon: '🛰️' },
                { id: 'v2rayn', name: 'v2rayN', icon: '🪟' },
                { id: 'v2raya', name: 'v2rayA', icon: '🧩' },
                { id: 'httpDynamic', name: 'HTTP 动态', icon: '🚪' }
            ],
			cfGlobalStatus: null,
			isLoadingSync: false,
            luckmailManualQty: 1,
            luckmailManualAutoTag: false,
            isManualBuying: false,
			cfRoutes: [],
            heroSmsBalance: '0.00',
            heroSmsPrices: [],
            isLoadingBalance: false,
            isLoadingPrices: false,
            selectedCfRoutes: [],
			cfGlobalStatusList: [],
			cfStatusTimer: null,
            isLoadingCfRoutes: false,
			isDeletingAccounts: false,
			isDeletingCfRoutes: false,
			subDomainModal: {
				show: false,
				email: '',
				key: '',
				count: 10,
				sync: false,
				loading: false
			},
			tempSubDomains: [],
            logs: [],
            logBuffer: [],
            logFlushTimer: null,
            config: null,
            blacklistStr: "",
            warpListStr: "",
            httpDynamicListStr: "",
            clashPoolSubUrl: '',
            clashPoolStatusOutput: '',
            clashPoolInfo: null,
            clashPoolGroups: [],
            clashPoolGroupError: '',
            clashPoolRuntime: null,
            clashPoolRuntimeError: '',
            isClashPoolUpdating: false,
            isProxyBatchChecking: false,
            isV2raynSubscriptionUpdating: false,
            isV2rayATesting: false,
            isUpdatePackageDownloading: false,
            isUpdatePackagesLoading: false,
            migratingUpdateVersion: '',
            isProjectUpdateChecking: false,
            isProjectUpdating: false,
            isV2rayAInspecting: false,
            isV2rayANodesLoading: false,
            isV2rayALatencyLoading: false,
            isV2rayAInvalidMutating: false,
            switchingV2rayANodeKey: '',
            v2rayARuntime: null,
            v2rayANodes: [],
            v2rayAStatusMessage: '',
            v2rayADuplicateGroups: [],
            v2rayAInvalidKeys: [],
            v2rayAListMode: 'all',
            v2rayAGroupFilter: 'all',
            v2rayAPage: 1,
            v2rayAPageSize: 12,
            v2rayAGroupPage: 1,
            v2rayAGroupPageSize: 10,
            projectUpdateStatus: null,
            updatePackages: [],
            logStreamStatus: '未连接',
            logStreamLastError: '',
            accounts: [],
            selectedAccounts: [],
			currentPage: 1,
            pageSize: 10,
            totalAccounts: 0,
            evtSource: null,
            stats: {
                success: 0, failed: 0, retries: 0, total: 0, target: 0,
                pwd_blocked: 0, phone_verify: 0,
                success_rate: '0.0%', elapsed: '0.0s', avg_time: '0.0s', progress_pct: '0%',
                mode: '未启动'
            },
            statsTimer: null,

            showPwd: {
                login: false, web: false, cf: false, imap: false, 
                free_token: false, free_pass: false,
                cm: false, mc: false, clash: false, cpa: false, sub2api: false,
                cf_key: false, cf_modal_key: false,
                mail_domains: true, cf_email: true, gpt_base: true, imap_user: true,
                free_url: true, cm_url: true, cm_email: true, mc_base: true,
                ai_base: true, cluster_url: true, proxy: true, clash_api: true,
                clash_test: true, tg_token: false, tg_chatid: false, cpa_url: true, sub_url: true,
                cluster_secret: false, hero_key: false, duck_token: false, duck_cookie: false,
                luckmail: false,
                temporam: false,
                tmailor_token: false,
                fvia_token: false,
                master_rt: false,
                clash_sub: false,
                v2raya_password: false
            },

            toasts: [],
            toastId: 0,
            confirmModal: { show: false, message: '', resolve: null },
            updateInfo: { hasUpdate: false, version: '', url: '', changelog: '' },
            sub2apiGroups: [],
            webProcessInfo: null,
            showWebProcessPanel: false,
            gmailOAuth: {
                authUrl: '',
                pastedCode: '',
                isLoading: false,
                isGenerating: false
            },
            isLoadingSub2APIGroups: false,
            cloudAccounts: [],
            selectedCloud: [],
            cloudFilters: ['sub2api', 'cpa'],
            showCloudPlaintext: false,
            cloudPage: 1,
            cloudPageSize: 10,
            cloudTotal: 0,
            localCheckTimes: {},
            localCloudDetails: {},
            isCloudActionLoading: false,
            showCloudDetailModal: false,
            currentCloudDetail: null,
            nowTimestamp: Math.floor(Date.now() / 1000),
            clusterNodes: {},
            selectedClusterNodeName: '',
            clusterVisibilityMap: {},
            clusterSearchKeyword: '',
            clusterShowOnlineOnly: false,
            isExtConnected: false,
        };
    },
    mounted() {
        if (this.isLoggedIn) {
            this.initApp();
        }
        window.addEventListener('hashchange', () => {
            const tab = window.location.hash.replace('#', '');
            if (tab && this.tabs.some(t => t.id === tab)) {
                this.currentTab = tab;
            }
        });
        this.timer = setInterval(() => {
            this.nowTimestamp = Math.floor(Date.now() / 1000);
        }, 1000);
    },
    beforeUnmount() {
        if(this.statsTimer) clearInterval(this.statsTimer);
    },
	computed: {
        totalPages() {
            return Math.ceil(this.totalAccounts / this.pageSize) || 1;
        },
        cloudTotalPages() {
            return Math.ceil(this.cloudTotal / this.cloudPageSize) || 1;
        },
        clusterNodeEntries() {
            const keyword = String(this.clusterSearchKeyword || '').trim().toLowerCase();
            return Object.entries(this.clusterNodes || {}).filter(([name, node]) => {
                const online = this.isClusterNodeOnline(node || {});
                if (this.clusterShowOnlineOnly && !online) return false;
                if (!keyword) return true;
                const mode = String((node?.stats?.mode) || '').toLowerCase();
                return String(name || '').toLowerCase().includes(keyword) || mode.includes(keyword);
            }).sort((a, b) => {
                const aNode = a[1] || {};
                const bNode = b[1] || {};
                const aOnline = this.isClusterNodeOnline(aNode);
                const bOnline = this.isClusterNodeOnline(bNode);
                if (aOnline !== bOnline) return aOnline ? -1 : 1;
                return String(a[0] || '').localeCompare(String(b[0] || ''), 'zh-CN');
            });
        },
        clusterTotalCount() {
            return Object.keys(this.clusterNodes || {}).length;
        },
        clusterOnlineCount() {
            return Object.values(this.clusterNodes || {}).filter(node => this.isClusterNodeOnline(node || {})).length;
        },
        clusterVisibleDetailCount() {
            return this.clusterNodeEntries.filter(([name]) => this.isClusterNodeVisible(name)).length;
        },
        selectedClusterNodeIndex() {
            return this.clusterNodeEntries.findIndex(([name]) => name === this.selectedClusterNodeName);
        },
        previousClusterNodeName() {
            const idx = this.selectedClusterNodeIndex;
            if (idx <= 0) return '';
            return this.clusterNodeEntries[idx - 1]?.[0] || '';
        },
        nextClusterNodeName() {
            const idx = this.selectedClusterNodeIndex;
            if (idx < 0 || idx >= this.clusterNodeEntries.length - 1) return '';
            return this.clusterNodeEntries[idx + 1]?.[0] || '';
        },
        selectedClusterNode() {
            const name = this.selectedClusterNodeName;
            if (!name || !this.clusterNodes || !this.clusterNodes[name]) return null;
            if (!this.isClusterNodeVisible(name)) return null;
            return this.clusterNodes[name];
        },
        v2rayASubscriptionTabs() {
            const groups = new Map();
            for (const node of (this.v2rayANodes || [])) {
                const key = String(node.subscription_id || node.subscription_name || 'ungrouped');
                const existing = groups.get(key) || {
                    key,
                    name: String(node.subscription_name || node.subscription_id || '未分组'),
                    count: 0,
                };
                existing.count += 1;
                groups.set(key, existing);
            }
            return Array.from(groups.values()).sort((a, b) => {
                if (b.count !== a.count) return b.count - a.count;
                return String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN');
            });
        },
        v2rayAFilteredNodes() {
            if (this.v2rayAGroupFilter === 'all') {
                return this.v2rayANodes || [];
            }
            return (this.v2rayANodes || []).filter(node => {
                const key = String(node.subscription_id || node.subscription_name || 'ungrouped');
                return key === this.v2rayAGroupFilter;
            });
        },
        v2rayATotalPages() {
            return Math.max(1, Math.ceil((this.v2rayAFilteredNodes || []).length / this.v2rayAPageSize));
        },
        v2rayAPagedNodes() {
            const currentPage = Math.min(Math.max(1, this.v2rayAPage), this.v2rayATotalPages);
            const start = (currentPage - 1) * this.v2rayAPageSize;
            return (this.v2rayAFilteredNodes || []).slice(start, start + this.v2rayAPageSize);
        },
        v2rayAGroupedSubscriptions() {
            const groups = new Map();
            for (const node of (this.v2rayANodes || [])) {
                const key = String(node.subscription_id || node.subscription_name || 'ungrouped');
                const existing = groups.get(key) || {
                    key,
                    name: String(node.subscription_name || node.subscription_id || '未分组'),
                    nodeCount: 0,
                    currentCount: 0,
                    bestLatency: null,
                };
                existing.nodeCount += 1;
                if (node.is_current) {
                    existing.currentCount += 1;
                }
                const latency = Number(node.latency_ms);
                if (Number.isFinite(latency)) {
                    existing.bestLatency = existing.bestLatency === null ? latency : Math.min(existing.bestLatency, latency);
                }
                groups.set(key, existing);
            }
            return Array.from(groups.values()).sort((a, b) => {
                if (b.nodeCount !== a.nodeCount) return b.nodeCount - a.nodeCount;
                return String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN');
            });
        },
        v2rayAGroupTotalPages() {
            return Math.max(1, Math.ceil((this.v2rayAGroupedSubscriptions || []).length / this.v2rayAGroupPageSize));
        },
        v2rayAPagedGroups() {
            const currentPage = Math.min(Math.max(1, this.v2rayAGroupPage), this.v2rayAGroupTotalPages);
            const start = (currentPage - 1) * this.v2rayAGroupPageSize;
            return (this.v2rayAGroupedSubscriptions || []).slice(start, start + this.v2rayAGroupPageSize);
        }
    },
    methods: {
        showToast(message, type = 'info') {
            const id = this.toastId++;
            this.toasts.push({ id, message, type });
            setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 3500);
        },

        async customConfirm(message) {
            return new Promise((resolve) => {
                this.confirmModal = { show: true, message, resolve };
            });
        },
        handleConfirm(result) {
            if (this.confirmModal.resolve) this.confirmModal.resolve(result);
            this.confirmModal.show = false;
        },
        async authFetch(url, options = {}) {
            const token = localStorage.getItem('auth_token');
            if (!options.headers) options.headers = {};
            options.headers['Authorization'] = 'Bearer ' + token;
            if (options.body && typeof options.body === 'string') {
                options.headers['Content-Type'] = 'application/json';
            }
            const res = await fetch(url, options);
            if (res.status === 401) {
                this.logout();
                this.showToast("登录状态过期，请重新登录！", "warning");
                throw new Error("Unauthorized");
            }
            return res;
        },

        async handleLogin() {
            if(!this.loginPassword) { this.showToast("请输入密码！", "warning"); return; }
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: this.loginPassword })
                });
                const data = await res.json();
                if (data.status === 'success') {
					this.logs = [];
                    localStorage.setItem('auth_token', data.token); 
                    this.isLoggedIn = true;
                    this.initApp();
                    this.showToast("登录成功，欢迎回来！", "success");
                } else { this.showToast(data.message, "error"); }
            } catch (e) { this.showToast("登录请求失败，请检查后端服务。", "error"); }
        },
        logout() {
            localStorage.removeItem('auth_token');
            this.isLoggedIn = false;
            this.loginPassword = '';
			this.logs = [];
            this.logBuffer = [];
            Object.keys(this.showPwd).forEach(k => this.showPwd[k] = false);
			if(this.evtSource) {
                this.evtSource.close();
                this.evtSource = null;
            }
            this.logStreamStatus = '未连接';
            this.logStreamLastError = '';
            if(this.statsTimer) clearInterval(this.statsTimer);
            if (this._extDetectionTimer) clearInterval(this._extDetectionTimer);
            if (this._extDispatchTimer) clearTimeout(this._extDispatchTimer);
            this._extDetectionTimer = null;
            this._extDispatchTimer = null;
            this.isExtConnected = false;
            this.webProcessInfo = null;
        },
        async initApp() {
            await this.fetchConfig();
            this.loadClusterUiPrefs();
            this.fetchWebProcessInfo();
            this.fetchAccounts();
            this.initSSE();
            this.startStatsPolling();
            this.checkUpdate();
            if (this.config && this.config.reg_mode === 'extension') {
                this.listenToExtension();
            }
            if (this.currentTab === 'proxy') {
                this.loadProxyTabData();
            }
            if (this.currentTab === 'update') {
                this.loadUpdateCenterData(false);
            }
        },
        async fetchWebProcessInfo() {
            try {
                const res = await this.authFetch('/api/system/web_process_info');
                this.webProcessInfo = await res.json();
            } catch (e) {}
        },
        async copyText(text, successMessage = '已复制') {
            if (!text) return;
            try {
                if (navigator.clipboard?.writeText) {
                    await navigator.clipboard.writeText(text);
                } else {
                    const textarea = document.createElement('textarea');
                    textarea.value = text;
                    textarea.setAttribute('readonly', '');
                    textarea.style.position = 'absolute';
                    textarea.style.left = '-9999px';
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                }
                this.showToast(successMessage, 'success');
            } catch (e) {
                this.showToast('复制失败，请手动复制', 'error');
            }
        },
        openProjectVersionPage(url = '') {
            window.open(url || this.versionPageUrl, '_blank');
        },
        async triggerUpdateDownload(url = '', version = '') {
            const finalUrl = url || this.updateInfo.url;
            const finalVersion = version || this.updateInfo.version;
            if (!finalUrl || !finalVersion) {
                this.showToast('当前没有可下载的更新包', 'warning');
                return;
            }
            this.isUpdatePackageDownloading = true;
            try {
                const res = await this.authFetch('/api/system/download_update_package', {
                    method: 'POST',
                    body: JSON.stringify({
                        version: finalVersion,
                        download_url: finalUrl
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const extractDir = data.data?.extract_dir || '';
                    const suffix = extractDir ? `\n\n解压目录：${extractDir}` : '';
                    const confirmed = await this.customConfirm(`${data.message || '更新包已下载完成。'}${suffix}`);
                    if (confirmed && extractDir) {
                        await this.copyText(extractDir, '更新目录已复制');
                    }
                } else {
                    this.showToast(data.message || '下载更新包失败', 'error');
                }
            } catch (e) {
                this.showToast('下载更新包失败，请检查后端日志', 'error');
            } finally {
                this.isUpdatePackageDownloading = false;
            }
        },
        startStatsPolling() {
            if(this.statsTimer) clearTimeout(this.statsTimer);
            this.pollStats();
        },
        isClusterNodeVisible(nodeName) {
            return this.clusterVisibilityMap[nodeName] !== false;
        },
        isClusterNodeConnectionAllowed(node) {
            return node?.connection_allowed !== false;
        },
        loadClusterUiPrefs() {
            try {
                const raw = localStorage.getItem('cluster_ui_prefs');
                if (!raw) return;
                const data = JSON.parse(raw);
                if (data && typeof data === 'object') {
                    this.clusterVisibilityMap = data.visibility_map && typeof data.visibility_map === 'object' ? data.visibility_map : {};
                    this.clusterSearchKeyword = typeof data.search_keyword === 'string' ? data.search_keyword : '';
                    this.clusterShowOnlineOnly = !!data.show_online_only;
                }
            } catch (e) {}
        },
        persistClusterUiPrefs() {
            try {
                localStorage.setItem('cluster_ui_prefs', JSON.stringify({
                    visibility_map: this.clusterVisibilityMap || {},
                    search_keyword: this.clusterSearchKeyword || '',
                    show_online_only: !!this.clusterShowOnlineOnly,
                }));
            } catch (e) {}
        },
        isClusterNodeOnline(node) {
            if (!node || !node.last_seen) return false;
            return (this.nowTimestamp - Math.floor(node.last_seen)) < 20;
        },
        syncClusterNodeSelection() {
            const entries = this.clusterNodeEntries || [];
            const validNames = new Set(entries.map(([name]) => name));
            Object.keys(this.clusterVisibilityMap || {}).forEach((name) => {
                if (!validNames.has(name)) {
                    delete this.clusterVisibilityMap[name];
                }
            });
            if (this.selectedClusterNodeName && validNames.has(this.selectedClusterNodeName) && this.isClusterNodeVisible(this.selectedClusterNodeName)) {
                return;
            }
            const fallback = entries.find(([name]) => this.isClusterNodeVisible(name));
            this.selectedClusterNodeName = fallback ? fallback[0] : '';
        },
        selectClusterNode(nodeName) {
            if (!nodeName || !this.clusterNodes[nodeName]) return;
            if (!this.isClusterNodeVisible(nodeName)) {
                this.clusterVisibilityMap[nodeName] = true;
                this.persistClusterUiPrefs();
            }
            this.selectedClusterNodeName = nodeName;
        },
        toggleClusterNodeVisibility(nodeName) {
            const nextVisible = !this.isClusterNodeVisible(nodeName);
            this.clusterVisibilityMap[nodeName] = nextVisible;
            this.persistClusterUiPrefs();
            if (!nextVisible && this.selectedClusterNodeName === nodeName) {
                this.syncClusterNodeSelection();
            }
            if (nextVisible && !this.selectedClusterNodeName) {
                this.selectedClusterNodeName = nodeName;
            }
        },
        goToPreviousClusterNode() {
            if (this.previousClusterNodeName) {
                this.selectClusterNode(this.previousClusterNodeName);
            }
        },
        goToNextClusterNode() {
            if (this.nextClusterNodeName) {
                this.selectClusterNode(this.nextClusterNodeName);
            }
        },
        showAllClusterNodeDetails() {
            for (const [name] of this.clusterNodeEntries) {
                this.clusterVisibilityMap[name] = true;
            }
            this.persistClusterUiPrefs();
            this.syncClusterNodeSelection();
        },
        hideAllClusterNodeDetails() {
            for (const [name] of this.clusterNodeEntries) {
                this.clusterVisibilityMap[name] = false;
            }
            this.persistClusterUiPrefs();
            this.syncClusterNodeSelection();
        },
        async pollStats() {
            if(!this.isLoggedIn) return;
            try {
                const res = await this.authFetch('/api/stats');
                const data = await res.json();
                this.stats = data;
                this.isRunning = data.is_running;
                if (this.currentTab === 'cluster') {
                    const cRes = await this.authFetch('/api/cluster/view');
                    const cData = await cRes.json();
                    if (cData.status === 'success') {
                        this.clusterNodes = cData.nodes;
                        this.syncClusterNodeSelection();
                    }
                }
            } catch(e) {

            } finally {
                this.statsTimer = setTimeout(() => {
                    this.pollStats();
                }, 1000);
            }
        },
        async fetchConfig() {
            try {
                const res = await this.authFetch('/api/config');
                this.config = await res.json();
                if (!this.config.tg_bot) {
                    this.config.tg_bot = { enable: false, token: '', chat_id: '' };
                }
                if (!this.config.tg_bot.template_success) {
                    this.config.tg_bot.template_success = "🎉 <b>注册成功</b>\n━━━━━━━━━━━━\n⏰ 时间：<code>{time}</code>\n📧 账号：<code>{email}</code>\n🔑 密码：<code>{password}</code>";
                }
                if (!this.config.tg_bot.template_stop) {
                    this.config.tg_bot.template_stop = "🛑 <b>任务已停止</b>\n━━━━━━━━━━━━\n📊 成功率：<code>{success_rate}%</code>\n✅ 成功：<code>{success}/{target}</code>\n❌ 失败：<code>{failed}</code>\n🚧 风控：<code>{retries}</code>\n🔒 密码受阻：<code>{pwd_blocked}</code>\n📱 出现手机：<code>{phone_verify}</code>\n⏱ 总耗时：<code>{elapsed_time}s</code>\n📈 平均单号：<code>{avg_time}s</code>";
                }
                if (this.config.tg_bot.use_proxy === undefined) {
                    this.config.tg_bot.use_proxy = false;
                }
                if (!this.config.luckmail) {
                    this.config.luckmail = {};
                }
                if (!this.config.local_microsoft) {
                    this.config.local_microsoft = {
                        enable_fission: false,
                        pool_fission: false,
                        master_email: '',
                        client_id: '',
                        refresh_token: ''
                    };
                }
                if (this.config.luckmail.use_imported_pool === undefined) {
                    this.config.luckmail.use_imported_pool = false;
                }
                if (!this.config.fvia) {
                    this.config.fvia = { token: '' };
                }
                if (!this.config.tmailor) {
                    this.config.tmailor = { current_token: '' };
                }
                if (!this.config.temporam) {
                    this.config.temporam = { cookie: '' };
                }
                if (!this.config.reg_mode) {
                    this.config.reg_mode = 'protocol';
                }
                if (this.config.luckmail.specified_email === undefined) {
                    this.config.luckmail.specified_email = '';
                }
                if (!this.config.http_dynamic_proxy) {
                    this.config.http_dynamic_proxy = { enable: false, pool_size: 3, proxy_list: [] };
                }
                if (!this.config.clash_proxy_pool) {
                    this.config.clash_proxy_pool = {};
                }
                if (!this.config.http_dynamic_proxy_runtime) {
                    this.config.http_dynamic_proxy_runtime = {
                        enabled: false,
                        configured_pool_size: 0,
                        source_count: 0,
                        loaded_channels: 0,
                        using_default_fallback: false,
                        single_source_cloned: false,
                        mode: 'disabled',
                        queue_ready: false,
                        error: '',
                        message: ''
                    };
                }
                if (this.config.http_dynamic_proxy.pool_size === undefined) {
                    this.config.http_dynamic_proxy.pool_size = 3;
                }
                if (!Array.isArray(this.config.http_dynamic_proxy.proxy_list)) {
                    this.config.http_dynamic_proxy.proxy_list = [];
                }
                if (!this.config.hero_sms) {
                    this.config.hero_sms = {};
                }
                if (this.config.hero_sms.use_proxy === undefined) {
                    this.config.hero_sms.use_proxy = false;
                }
				if (!this.config.sub_domain_level) {
                    this.config.sub_domain_level = 1;
                }
                if (!this.config.sub2api_mode) {
                    this.config.sub2api_mode = {};
                }
                if (this.config.sub2api_mode.account_concurrency === undefined) {
                    this.config.sub2api_mode.account_concurrency = 10;
                }
                if (this.config.sub2api_mode.account_load_factor === undefined) {
                    this.config.sub2api_mode.account_load_factor = 10;
                }
                if (this.config.sub2api_mode.account_priority === undefined) {
                    this.config.sub2api_mode.account_priority = 1;
                }
                if (this.config.sub2api_mode.account_rate_multiplier === undefined) {
                    this.config.sub2api_mode.account_rate_multiplier = 1.0;
                }
                if (this.config.sub2api_mode.account_group_ids === undefined) {
                    this.config.sub2api_mode.account_group_ids = '';
                }
                if (this.config.sub2api_mode.enable_ws_mode === undefined) {
                    this.config.sub2api_mode.enable_ws_mode = true;
                }
                if (this.config.sub2api_mode.use_proxy === undefined) {
                    this.config.sub2api_mode.use_proxy = false;
                }
                if (this.config.clash_proxy_pool.client_type === undefined) this.config.clash_proxy_pool.client_type = 'clash';
                if (this.config.clash_proxy_pool.v2raya_url === undefined) this.config.clash_proxy_pool.v2raya_url = '';
                if (this.config.clash_proxy_pool.v2raya_username === undefined) this.config.clash_proxy_pool.v2raya_username = '';
                if (this.config.clash_proxy_pool.v2raya_password === undefined) this.config.clash_proxy_pool.v2raya_password = '';
                if (this.config.clash_proxy_pool.v2raya_xray_bin === undefined) this.config.clash_proxy_pool.v2raya_xray_bin = '';
                if (this.config.clash_proxy_pool.v2raya_assets_dir === undefined) this.config.clash_proxy_pool.v2raya_assets_dir = '';
                if (this.config.clash_proxy_pool.v2raya_env_file === undefined) this.config.clash_proxy_pool.v2raya_env_file = '';
                if (this.config.clash_proxy_pool.v2rayn_base_dir === undefined) this.config.clash_proxy_pool.v2rayn_base_dir = '';
                if (this.config.clash_proxy_pool.v2rayn_restart_wait_sec === undefined) this.config.clash_proxy_pool.v2rayn_restart_wait_sec = 15;
                if (this.config.clash_proxy_pool.v2rayn_hide_window_on_restart === undefined) this.config.clash_proxy_pool.v2rayn_hide_window_on_restart = true;
                if (this.config.clash_proxy_pool.v2rayn_precheck_on_start === undefined) this.config.clash_proxy_pool.v2rayn_precheck_on_start = true;
                if (this.config.clash_proxy_pool.v2rayn_precheck_cache_minutes === undefined) this.config.clash_proxy_pool.v2rayn_precheck_cache_minutes = 30;
                if (this.config.clash_proxy_pool.v2rayn_precheck_max_nodes === undefined) this.config.clash_proxy_pool.v2rayn_precheck_max_nodes = 12;
                if (this.config.clash_proxy_pool.v2rayn_subscription_update_enabled === undefined) this.config.clash_proxy_pool.v2rayn_subscription_update_enabled = false;
                if (this.config.clash_proxy_pool.v2rayn_subscription_update_interval_minutes === undefined) this.config.clash_proxy_pool.v2rayn_subscription_update_interval_minutes = 180;
                if (this.config.clash_proxy_pool.v2rayn_subscription_update_command === undefined) this.config.clash_proxy_pool.v2rayn_subscription_update_command = '';
                if(this.config.clash_proxy_pool && Array.isArray(this.config.clash_proxy_pool.blacklist)) {
                    this.blacklistStr = this.config.clash_proxy_pool.blacklist.join('\n');
                }
                if(Array.isArray(this.config.warp_proxy_list)) {
                    this.warpListStr = this.config.warp_proxy_list.join('\n');
                }
                if(Array.isArray(this.config.http_dynamic_proxy.proxy_list)) {
                    this.httpDynamicListStr = this.config.http_dynamic_proxy.proxy_list.join('\n');
                }
                if (this.config.cluster_node_name === undefined) this.config.cluster_node_name = '';
                if (this.config.cluster_master_url === undefined) this.config.cluster_master_url = '';
                if (this.config.cluster_secret === undefined) this.config.cluster_secret = 'change-me-cluster-secret';
                if (!this.proxySubTabs.some(item => item.id === this.proxySubTab)) {
                    this.proxySubTab = 'general';
                }
            } catch (e) {}
        },
        async fetchClashPoolInfo() {
            try {
                const res = await this.authFetch('/api/clash_pool/info');
                const data = await res.json();
                if (data.status === 'success') {
                    this.clashPoolInfo = data.data || {};
                    this.clashPoolSubUrl = (data.data && (data.data.effective_sub_url || data.data.sub_url)) ? (data.data.effective_sub_url || data.data.sub_url) : '';
                    this.clashPoolStatusOutput = (data.data && data.data.status_output) ? data.data.status_output : '';
                    this.clashPoolGroups = (data.data && Array.isArray(data.data.group_candidates)) ? data.data.group_candidates : [];
                    this.clashPoolGroupError = (data.data && data.data.group_error) ? data.data.group_error : '';
                    this.clashPoolRuntime = (data.data && data.data.runtime_status) ? data.data.runtime_status : null;
                    this.clashPoolRuntimeError = (data.data && data.data.runtime_error) ? data.data.runtime_error : '';
                } else {
                    this.showToast(data.message || '读取 Clash 订阅信息失败', 'warning');
                }
            } catch (e) {
                this.showToast('读取 Clash 订阅信息失败', 'error');
            }
        },
        async updateClashPoolSubscription() {
            const subUrl = (this.clashPoolSubUrl || '').trim();
            if (!subUrl) {
                this.showToast('请先填写 Clash 订阅链接', 'warning');
                return;
            }
            const confirmed = await this.customConfirm('确认更新 Clash 订阅并重载整个代理池吗？');
            if (!confirmed) return;
            this.isClashPoolUpdating = true;
            try {
                const res = await this.authFetch('/api/clash_pool/update_subscription', {
                    method: 'POST',
                    body: JSON.stringify({ sub_url: subUrl })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const effectiveSubUrl = (data.data && data.data.effective_sub_url) ? data.data.effective_sub_url : subUrl;
                    this.clashPoolStatusOutput = data.status_output || data.output || '';
                    this.clashPoolSubUrl = effectiveSubUrl;
                    if (this.clashPoolInfo) {
                        this.clashPoolInfo.sub_url = effectiveSubUrl;
                        this.clashPoolInfo.effective_sub_url = effectiveSubUrl;
                        this.clashPoolInfo.status_output = this.clashPoolStatusOutput;
                    }
                    this.clashPoolGroups = Array.isArray(data.group_candidates) ? data.group_candidates : this.clashPoolGroups;
                    this.clashPoolGroupError = data.group_error || '';
                    this.clashPoolRuntime = data.runtime_status || this.clashPoolRuntime;
                    this.clashPoolRuntimeError = data.runtime_error || '';
                    this.showToast(data.message || 'Clash 订阅更新成功', 'success');
                    await this.fetchClashPoolInfo();
                } else {
                    if (data.data && data.data.sub_url) {
                        this.clashPoolSubUrl = data.data.sub_url;
                    }
                    this.clashPoolStatusOutput = data.output || data.status_output || this.clashPoolStatusOutput;
                    this.clashPoolGroups = Array.isArray(data.group_candidates) ? data.group_candidates : this.clashPoolGroups;
                    this.clashPoolGroupError = data.group_error || '';
                    this.clashPoolRuntime = data.runtime_status || this.clashPoolRuntime;
                    this.clashPoolRuntimeError = data.runtime_error || '';
                    this.showToast(data.message || 'Clash 订阅更新失败', 'error');
                }
            } catch (e) {
                this.showToast('Clash 订阅更新失败，请检查后端日志', 'error');
            } finally {
                this.isClashPoolUpdating = false;
            }
        },
        useClashGroupName(name) {
            if (!this.config || !this.config.clash_proxy_pool) return;
            this.config.clash_proxy_pool.group_name = name || '';
            this.showToast(`已填入策略组：${name}`, 'success');
        },
        handleClashEnableToggle() {
            if (!this.config || !this.config.clash_proxy_pool) return;
            if (this.config.clash_proxy_pool.enable && this.config.http_dynamic_proxy?.enable) {
                this.config.http_dynamic_proxy.enable = false;
                this.showToast('已自动关闭 HTTP 动态代理池，避免与 Clash 智能切点同时开启', 'warning');
            }
        },
        handleHttpDynamicToggle() {
            if (!this.config || !this.config.http_dynamic_proxy) return;
            if (this.config.http_dynamic_proxy.enable && this.config.clash_proxy_pool?.enable) {
                this.config.clash_proxy_pool.enable = false;
                this.showToast('已自动关闭 Clash 智能切点，避免与 HTTP 动态代理池同时开启', 'warning');
            }
        },
        getProxyClientTab(clientType) {
            const key = String(clientType || '').trim().toLowerCase();
            if (key === 'v2rayn') return 'v2rayn';
            if (key === 'v2raya') return 'v2raya';
            return 'clash';
        },
        switchProxySubTab(tabId) {
            this.proxySubTab = tabId;
            if (tabId === 'clash') {
                this.fetchClashPoolInfo();
            }
            if (tabId === 'v2raya') {
                this.inspectV2rayAEnvironment(false);
                this.fetchV2rayANodes(false, false);
            }
        },
        loadProxyTabData() {
            if (!this.config?.clash_proxy_pool) return;
            if (this.proxySubTab === 'clash' || this.config.clash_proxy_pool.client_type === 'clash') {
                this.fetchClashPoolInfo();
            }
            if (this.proxySubTab === 'v2raya') {
                this.inspectV2rayAEnvironment(false);
                this.fetchV2rayANodes(false, false);
            }
        },
        handleProxyClientTypeChange() {
            if (!this.config?.clash_proxy_pool) return;
            this.proxySubTab = this.getProxyClientTab(this.config.clash_proxy_pool.client_type);
            this.loadProxyTabData();
        },
        async saveConfig(showSuccess = true) {
            try {
                if(this.config.clash_proxy_pool) {
                    this.config.clash_proxy_pool.blacklist = this.blacklistStr.split('\n').map(s => s.trim()).filter(s => s);
                }
                this.config.warp_proxy_list = this.warpListStr.split('\n').map(s => s.trim()).filter(s => s);
                if (!this.config.http_dynamic_proxy) {
                    this.config.http_dynamic_proxy = {};
                }
                this.config.http_dynamic_proxy.proxy_list = this.httpDynamicListStr.split('\n').map(s => s.trim()).filter(s => s);
                const res = await this.authFetch('/api/config', {
                    method: 'POST', body: JSON.stringify(this.config)
                });
                const data = await res.json();
                if(data.status === 'success') {
                    if (showSuccess) {
                        this.showToast(data.message, "success");
                    }
                    await this.fetchConfig();
                    this.pollStats();
                } else { this.showToast("保存失败：" + data.message, "error"); }
            } catch (e) { this.showToast("保存失败网络异常", "error"); }
        },
        async runV2raynPrecheck(refreshSubscription = false) {
            if (this.isRunning) {
                this.showToast('请先停止当前运行的任务', 'warning');
                return;
            }
            if (!this.config?.clash_proxy_pool || this.config.clash_proxy_pool.client_type !== 'v2rayn') {
                this.showToast('当前不是 v2rayN 模式', 'warning');
                return;
            }
            this.isProxyBatchChecking = true;
            this.currentTab = 'console';
            this.showToast(refreshSubscription ? '正在更新订阅并重新筛选可用节点...' : '正在重新筛选可用节点...', 'info');
            try {
                await this.saveConfig(false);
                const suffix = refreshSubscription ? '?refresh_subscription=true' : '';
                const res = await this.authFetch(`/api/proxy/v2rayn/precheck${suffix}`, { method: 'POST' });
                const data = await res.json();
                const level = data.status === 'success' ? 'success' : (data.status === 'warning' ? 'warning' : 'error');
                this.showToast(data.message || 'v2rayN 可用节点筛选已完成', level);
            } catch (e) {
                this.showToast('v2rayN 节点筛选请求失败', 'error');
            } finally {
                this.isProxyBatchChecking = false;
            }
        },
        async runV2raynSubscriptionUpdateOnly() {
            if (!this.config?.clash_proxy_pool || this.config.clash_proxy_pool.client_type !== 'v2rayn') {
                this.showToast('当前不是 v2rayN 模式', 'warning');
                return;
            }
            this.isV2raynSubscriptionUpdating = true;
            this.showToast('正在更新 v2rayN 订阅...', 'info');
            try {
                await this.saveConfig(false);
                const res = await this.authFetch('/api/proxy/v2rayn/update_subscription', { method: 'POST' });
                const data = await res.json();
                const level = data.status === 'success' ? 'success' : (data.status === 'warning' ? 'warning' : 'error');
                this.showToast(data.message || 'v2rayN 订阅更新已完成，下次切换节点时会自动重筛。', level);
            } catch (e) {
                this.showToast('v2rayN 订阅更新请求失败', 'error');
            } finally {
                this.isV2raynSubscriptionUpdating = false;
            }
        },
        openV2rayAPanel() {
            const url = (this.config?.clash_proxy_pool?.v2raya_url || '').trim();
            if (!url) {
                this.showToast('请先填写 v2rayA 面板地址', 'warning');
                return;
            }
            window.open(url, '_blank');
        },
        async testV2rayACurrentProxy() {
            if (!this.config?.clash_proxy_pool || this.config.clash_proxy_pool.client_type !== 'v2raya') {
                this.showToast('当前不是 v2rayA 模式', 'warning');
                return;
            }
            this.isV2rayATesting = true;
            try {
                await this.saveConfig(false);
                const res = await this.authFetch('/api/proxy/v2raya/test_current', { method: 'POST' });
                const data = await res.json();
                const level = data.status === 'success' ? 'success' : (data.status === 'warning' ? 'warning' : 'error');
                this.showToast(data.message || 'v2rayA 当前链路检测已完成', level);
            } catch (e) {
                this.showToast('v2rayA 当前链路检测失败', 'error');
            } finally {
                this.isV2rayATesting = false;
            }
        },
        async inspectV2rayAEnvironment(showToast = true) {
            if (!this.config?.clash_proxy_pool || this.config.clash_proxy_pool.client_type !== 'v2raya') {
                if (showToast) {
                    this.showToast('当前不是 v2rayA 模式', 'warning');
                }
                return;
            }
            this.isV2rayAInspecting = true;
            try {
                await this.saveConfig(false);
                const res = await this.authFetch('/api/proxy/v2raya/inspect', { method: 'POST' });
                const data = await res.json();
                this.v2rayARuntime = data.data || null;
                if (showToast) {
                    const level = data.status === 'success' ? 'success' : (data.status === 'warning' ? 'warning' : 'error');
                    this.showToast(data.message || 'v2rayA 环境检测已完成', level);
                }
            } catch (e) {
                if (showToast) {
                    this.showToast('v2rayA 环境检测失败', 'error');
                }
            } finally {
                this.isV2rayAInspecting = false;
            }
        },
        getV2rayANodeKey(node) {
            if (!node) return '';
            return [node.node_type || 'server', node.subscription_id || '-', node.node_id || node.name || 'unknown'].join(':');
        },
        formatV2rayALatency(node) {
            if (!node || node.latency_ms === null || node.latency_ms === undefined || node.latency_ms === '') {
                return '--';
            }
            const value = Number(node.latency_ms);
            if (Number.isNaN(value)) {
                return String(node.latency_ms);
            }
            return `${value.toFixed(value >= 100 ? 0 : 1)} ms`;
        },
        getV2rayAStatusMeta(node) {
            if (!node) return { text: '未知', className: 'bg-slate-50 text-slate-600 border-slate-200' };
            if (node.is_current) {
                return { text: '当前节点', className: 'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200' };
            }
            if (node.is_invalid) {
                return { text: '失效标记', className: 'bg-rose-100 text-rose-700 border-rose-200' };
            }
            if (node.is_duplicate) {
                return { text: '重复节点', className: 'bg-amber-100 text-amber-700 border-amber-200' };
            }
            return { text: '候选节点', className: 'bg-slate-50 text-slate-600 border-slate-200' };
        },
        sortV2rayANodes(nodes) {
            return [...(nodes || [])].sort((a, b) => {
                if (!!a.is_current !== !!b.is_current) return a.is_current ? -1 : 1;
                if (!!a.is_invalid !== !!b.is_invalid) return a.is_invalid ? 1 : -1;
                if (!!a.is_duplicate !== !!b.is_duplicate) return a.is_duplicate ? 1 : -1;
                const aLatency = Number.isFinite(Number(a.latency_ms)) ? Number(a.latency_ms) : Number.POSITIVE_INFINITY;
                const bLatency = Number.isFinite(Number(b.latency_ms)) ? Number(b.latency_ms) : Number.POSITIVE_INFINITY;
                if (aLatency !== bLatency) return aLatency - bLatency;
                const aSub = String(a.subscription_name || '');
                const bSub = String(b.subscription_name || '');
                if (aSub !== bSub) return aSub.localeCompare(bSub, 'zh-CN');
                return String(a.name || a.address || a.node_id || '').localeCompare(String(b.name || b.address || b.node_id || ''), 'zh-CN');
            });
        },
        changeV2rayAPage(nextPage) {
            const target = Math.min(this.v2rayATotalPages, Math.max(1, Number(nextPage) || 1));
            this.v2rayAPage = target;
        },
        changeV2rayAGroupPage(nextPage) {
            const target = Math.min(this.v2rayAGroupTotalPages, Math.max(1, Number(nextPage) || 1));
            this.v2rayAGroupPage = target;
        },
        changeV2rayAListMode(mode) {
            this.v2rayAListMode = mode === 'grouped' ? 'grouped' : 'all';
            this.v2rayAPage = 1;
            this.v2rayAGroupPage = 1;
        },
        selectV2rayAGroupFilter(groupKey) {
            this.v2rayAGroupFilter = groupKey || 'all';
            this.v2rayAListMode = 'all';
            this.v2rayAPage = 1;
        },
        applyV2rayANodesPayload(payload = {}) {
            this.v2rayANodes = this.sortV2rayANodes(Array.isArray(payload.nodes) ? payload.nodes : []);
            this.v2rayADuplicateGroups = Array.isArray(payload.duplicate_groups) ? payload.duplicate_groups : [];
            this.v2rayAInvalidKeys = Array.isArray(payload.invalid_keys) ? payload.invalid_keys : [];
            this.v2rayAPage = 1;
            this.v2rayAGroupPage = 1;
            if (this.v2rayAGroupFilter !== 'all' && !this.v2rayASubscriptionTabs.some(item => item.key === this.v2rayAGroupFilter)) {
                this.v2rayAGroupFilter = 'all';
            }
            this.v2rayAStatusMessage = payload.message || this.v2rayAStatusMessage;
            if (payload.runtime) {
                this.v2rayARuntime = payload.runtime;
            }
        },
        async fetchV2rayANodes(withLatency = false, showToast = true) {
            if (!this.config?.clash_proxy_pool || this.config.clash_proxy_pool.client_type !== 'v2raya') {
                if (showToast) {
                    this.showToast('当前不是 v2rayA 模式', 'warning');
                }
                return;
            }
            this.isV2rayANodesLoading = !withLatency;
            if (withLatency) {
                this.isV2rayALatencyLoading = true;
            }
            try {
                await this.saveConfig(false);
                const suffix = withLatency ? '?with_latency=true' : '';
                const res = await this.authFetch(`/api/proxy/v2raya/nodes${suffix}`);
                const data = await res.json();
                if (data.status === 'success' || data.status === 'warning') {
                    const payload = data.data || {};
                    this.v2rayAStatusMessage = payload.message || '';
                    this.applyV2rayANodesPayload(payload);
                    if (showToast) {
                        const level = data.status === 'success' ? 'success' : 'warning';
                        this.showToast(data.message || (withLatency ? 'v2rayA 节点延迟已刷新' : 'v2rayA 节点列表已刷新'), level);
                    }
                } else if (showToast) {
                    this.showToast(data.message || '读取 v2rayA 节点列表失败', 'error');
                }
            } catch (e) {
                if (showToast) {
                    this.showToast(withLatency ? '读取 v2rayA 节点延迟失败' : '读取 v2rayA 节点列表失败', 'error');
                }
            } finally {
                this.isV2rayANodesLoading = false;
                this.isV2rayALatencyLoading = false;
            }
        },
        async switchV2rayANode(node) {
            if (!node) return;
            if (!this.config?.clash_proxy_pool || this.config.clash_proxy_pool.client_type !== 'v2raya') {
                this.showToast('当前不是 v2rayA 模式', 'warning');
                return;
            }
            const nodeKey = this.getV2rayANodeKey(node);
            this.switchingV2rayANodeKey = nodeKey;
            try {
                await this.saveConfig(false);
                const res = await this.authFetch('/api/proxy/v2raya/switch', {
                    method: 'POST',
                    body: JSON.stringify({
                        node_id: node.node_id || '',
                        node_type: node.node_type || 'subscriptionServer',
                        subscription_id: node.subscription_id || '',
                        node_name: node.name || ''
                    })
                });
                const data = await res.json();
                if (data.status === 'success' || data.status === 'warning') {
                    const payload = data.data || {};
                    this.applyV2rayANodesPayload({ ...payload, message: payload.message || this.v2rayAStatusMessage });
                    const level = data.status === 'success' ? 'success' : 'warning';
                    this.showToast(data.message || 'v2rayA 节点切换已提交', level);
                } else {
                    this.showToast(data.message || 'v2rayA 节点切换失败', 'error');
                }
            } catch (e) {
                this.showToast('v2rayA 节点切换失败', 'error');
            } finally {
                this.switchingV2rayANodeKey = '';
            }
        },
        async markV2rayANodeInvalid(node) {
            if (!node?.key) return;
            this.isV2rayAInvalidMutating = true;
            try {
                const res = await this.authFetch('/api/proxy/v2raya/mark_invalid', {
                    method: 'POST',
                    body: JSON.stringify({ node_keys: [node.key] })
                });
                const data = await res.json();
                if (data.status === 'success' || data.status === 'warning') {
                    this.applyV2rayANodesPayload(data.data || {});
                    this.showToast(data.message || '节点已标记为失效', data.status === 'success' ? 'success' : 'warning');
                } else {
                    this.showToast(data.message || '标记失效失败', 'error');
                }
            } catch (e) {
                this.showToast('标记失效失败', 'error');
            } finally {
                this.isV2rayAInvalidMutating = false;
            }
        },
        async markV2rayANodesWithoutLatencyInvalid() {
            const nodeKeys = Array.from(new Set((this.v2rayANodes || [])
                .filter(node => !node?.is_current && !node?.is_invalid)
                .filter(node => node?.latency_ms === null || node?.latency_ms === undefined || node?.latency_ms === '' || Number.isNaN(Number(node?.latency_ms)))
                .map(node => node.key)
                .filter(Boolean)));
            if (!nodeKeys.length) {
                this.showToast('当前没有可标记的无延迟节点', 'warning');
                return;
            }
            this.isV2rayAInvalidMutating = true;
            try {
                const res = await this.authFetch('/api/proxy/v2raya/mark_invalid', {
                    method: 'POST',
                    body: JSON.stringify({ node_keys: nodeKeys })
                });
                const data = await res.json();
                if (data.status === 'success' || data.status === 'warning') {
                    this.applyV2rayANodesPayload(data.data || {});
                    this.showToast(data.message || `已将 ${nodeKeys.length} 个无延迟节点标记为失效`, data.status === 'success' ? 'success' : 'warning');
                } else {
                    this.showToast(data.message || '无延迟节点标记失败', 'error');
                }
            } catch (e) {
                this.showToast('无延迟节点标记失败', 'error');
            } finally {
                this.isV2rayAInvalidMutating = false;
            }
        },
        async clearV2rayAInvalidMarks() {
            this.isV2rayAInvalidMutating = true;
            try {
                const res = await this.authFetch('/api/proxy/v2raya/clear_invalid', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success' || data.status === 'warning') {
                    this.applyV2rayANodesPayload(data.data || {});
                    this.showToast(data.message || '已清空失效标记', data.status === 'success' ? 'success' : 'warning');
                } else {
                    this.showToast(data.message || '清空失效标记失败', 'error');
                }
            } catch (e) {
                this.showToast('清空失效标记失败', 'error');
            } finally {
                this.isV2rayAInvalidMutating = false;
            }
        },
        async dedupeV2rayANodes() {
            this.isV2rayAInvalidMutating = true;
            try {
                const res = await this.authFetch('/api/proxy/v2raya/dedupe', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success' || data.status === 'warning') {
                    this.applyV2rayANodesPayload(data.data || {});
                    this.showToast(data.message || '重复节点处理完成', data.status === 'success' ? 'success' : 'warning');
                } else {
                    this.showToast(data.message || '重复节点处理失败', 'error');
                }
            } catch (e) {
                this.showToast('重复节点处理失败', 'error');
            } finally {
                this.isV2rayAInvalidMutating = false;
            }
        },
		async fetchAccounts(isManual = false) {
            if (isManual) {
                this.currentPage = 1;
            }
            try {
                const res = await this.authFetch(`/api/accounts?page=${this.currentPage}&page_size=${this.pageSize}`);
                const data = await res.json();
                if(data.status === 'success') {
                    this.accounts = data.data ? data.data : data;
                    if (data.total !== undefined) {
                        this.totalAccounts = data.total;
                    } else {
                        this.totalAccounts = this.accounts.length;
                    }
                    
                    this.selectedAccounts = []; 
                    if (isManual) this.showToast("账号列表已刷新！", "success");
                }
            } catch (e) {
                console.error("获取账号列表失败:", e);
            }
        },
		changePage(newPage) {
            if (newPage < 1 || newPage > this.totalPages) return;
            this.currentPage = newPage;
            this.selectedAccounts = []; 
            this.fetchAccounts(false);
        },
		changePageSize() {
            this.currentPage = 1;
            
            this.selectedAccounts = []; 
            
            this.fetchAccounts(false);
        },
        switchTab(tabId) {
            this.currentTab = tabId;
            window.location.hash = tabId;
			if (tabId === 'console') {
				this.pollStats(); 
			}
            if (tabId === 'accounts') {
                this.fetchAccounts();
            }
            if (tabId === 'email') {
				this.fetchConfig();
			}
            if (tabId === 'proxy') {
                this.loadProxyTabData();
            }
            if (tabId === 'update') {
                this.loadUpdateCenterData(false);
            }
			if (tabId === 'cloud') {
			    this.fetchCloudAccounts();
			}
            if (tabId === 'cluster') {
                this.fetchLocalClusterStatus(false);
                this.initClusterWebSocket();
                this.syncClusterNodeSelection();
            } else {
                if (this.clusterWs) this.clusterWs.close();
            }
        },
        async exportSelectedAccounts() {
            if (this.selectedAccounts.length === 0) {
                this.showToast("请先勾选需要导出的账号", "warning");
                return;
            }

            const emails = this.selectedAccounts.map(acc => acc.email);

            try {
                const res = await this.authFetch('/api/accounts/export_selected', {
                    method: 'POST',
                    body: JSON.stringify({ emails: emails })
                });
                const result = await res.json();

                if (result.status === 'success') {
                    const data = result.data;
                    const timestamp = Math.floor(Date.now() / 1000);
                    if (data.length > 1) {
                        const zip = new JSZip();

                        data.forEach((tokenObj, index) => {
                            const accEmail = tokenObj.email || "unknown";
                            const parts = accEmail.split('@');
                            const prefix = parts[0] || "user";
                            const domain = parts[1] || "domain";

                            const filename = `token_${prefix}_${domain}_${timestamp + index}.json`;
                            zip.file(filename, JSON.stringify(tokenObj, null, 4));
                        });

                        const content = await zip.generateAsync({ type: "blob" });
                        const url = window.URL.createObjectURL(content);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `CPA_Batch_Export_${data.length}_${timestamp}.zip`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        window.URL.revokeObjectURL(url);

                        this.showToast(`🎉 成功打包导出 ${data.length} 个账号的压缩包！`, "success");
                    } else {
                        data.forEach((tokenObj, index) => {
                            setTimeout(() => {
                                const accEmail = tokenObj.email || "unknown";
                                const parts = accEmail.split('@');
                                const prefix = parts[0] || "user";
                                const domain = parts[1] || "domain";

                                const ts = Math.floor(Date.now() / 1000) + index;
                                const filename = `token_${prefix}_${domain}_${ts}.json`;
                                const jsonString = JSON.stringify(tokenObj, null, 4);
                                const blob = new Blob([jsonString], { type: 'application/json;charset=utf-8' });
                                const url = window.URL.createObjectURL(blob);

                                const a = document.createElement('a');
                                a.href = url;
                                a.download = filename;
                                document.body.appendChild(a);
                                a.click();
                                document.body.removeChild(a);
                                window.URL.revokeObjectURL(url);
                            }, index * 300);
                        });
                        this.showToast(`🎉 成功触发 ${data.length} 个独立 Token 文件的下载！`, "success");
                    }

                    this.selectedAccounts = [];
                } else {
                    this.showToast(result.message, "warning");
                }
            } catch (e) {
                console.error(e);
                this.showToast("导出请求失败，请检查网络或 JSZip 是否加载", "error");
            }
        },
		maskEmail(email) {
            if (!email) return '';
            const parts = email.split('@');
            if (parts.length !== 2) return '******'; 
            
            const name = parts[0];
            const maskedDomain = '***.***';
            
            if (name.length <= 3) {
                return name + '***@' + maskedDomain;
            }
            return name.substring(0, 3) + '***@' + maskedDomain;
        },
		exportAccountsToTxt() {
			if (this.selectedAccounts.length === 0) return;

			const textContent = this.selectedAccounts
				.map(acc => `${acc.email}----${acc.password}`)
				.join('\n');

			const blob = new Blob([textContent], { type: 'text/plain;charset=utf-8' });
			const url = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = url;
			
			const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
			link.download = `accounts_login_${dateStr}.txt`;
			
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
			URL.revokeObjectURL(url);

			this.showToast(`成功导出 ${this.selectedAccounts.length} 个账号到 TXT`, 'success');
		},
		async deleteSelectedAccounts() {
            if (this.selectedAccounts.length === 0) return;

            const confirmed = await this.customConfirm(`⚠️ 危险操作：\n\n确定要彻底删除选中的 ${this.selectedAccounts.length} 个账号吗？\n删除后数据将无法恢复！`);
            if (!confirmed) return;
			this.isDeletingAccounts = true;
            try {
                const emailsToDelete = this.selectedAccounts.map(acc => acc.email);
                
                const res = await this.authFetch('/api/accounts/delete', {
                    method: 'POST',
                    body: JSON.stringify({ emails: emailsToDelete })
                });
                
                const data = await res.json();
                
                if (data.status === 'success') {
                    this.showToast(`成功物理删除 ${emailsToDelete.length} 个账号`, 'success');
                    this.selectedAccounts = [];
                    this.fetchAccounts();
                } else {
                    this.showToast('删除失败: ' + data.message, 'error');
                }
            } catch (error) {
                this.showToast('删除请求异常，请检查后端', 'error');
            } finally {
				this.isDeletingAccounts = false;
			}
        },
        toggleAll(event) {
            if (event.target.checked) this.selectedAccounts = [...this.accounts];
            else this.selectedAccounts = [];
        },
        async dispatchExtensionTask() {
            if (!this.isRunning) return;
            try {
                const res = await this.authFetch('/api/ext/generate_task');
                const data = await res.json();
                if (!this.isRunning) {
                    this.showToast("任务已生成，但系统已停止，已丢弃该任务。", "warning");
                    return;
                }

                const now = new Date();
                const timeStr = now.toLocaleTimeString('zh-CN', { hour12: false });

                if (data.status !== 'success') {
                    this.logs.push({
                        parsed: true,
                        time: timeStr,
                        level: '总控',
                        text: `任务生成失败: ${data.message}`,
                        raw: `[${timeStr}] [总控] 任务生成失败: ${data.message}`
                    });
                    return;
                }

                const task = data.task_data;
                const taskId = "TASK_" + Date.now();
                this.logs.push({
                    parsed: true,
                    time: timeStr,
                    level: '总控',
                    text: `📦 古法任务已打包，目标邮箱: ${task.email}，正在下发到浏览器插件...`,
                    raw: `[${timeStr}] [总控] 📦 古法任务已打包，目标邮箱: ${task.email}，正在下发到浏览器插件...`
                });

                this.$nextTick(() => {
                    const container = document.getElementById('terminal-container');
                    if (container) container.scrollTop = container.scrollHeight;
                });

                window.postMessage({
                    type: "CMD_EXECUTE_TASK",
                    payload: {
                        taskId: taskId,
                        apiUrl: window.location.origin,
                        token: localStorage.getItem('auth_token'),
                        email: task.email,
                        email_jwt: task.email_jwt,
                        password: task.password,
                        firstName: task.firstName,
                        lastName: task.lastName,
                        birthday: task.birthday,
                        registerUrl: task.registerUrl,
                        code_verifier: task.code_verifier,
                        expected_state: task.expected_state
                    }
                }, "*");
            } catch (error) {
                const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false });
                this.logs.push({
                    parsed: true,
                    time: timeStr,
                    level: '总控',
                    text: `下发古法任务异常: ${error.message}`,
                    raw: `[${timeStr}] [总控] 下发古法任务异常: ${error.message}`
                });
            }
        },
        syncTokenToExtension() {
            const localWorkerId = localStorage.getItem('local_worker_id');
            if (!localWorkerId) return;
            window.postMessage({
                type: "CMD_INIT_NODE",
                payload: {
                    apiUrl: window.location.origin,
                    token: localStorage.getItem('auth_token'),
                    workerId: localWorkerId
                }
            }, "*");
            console.log(`📡 [总控] 身份同步指令已下发: ${localWorkerId}`);
        },
        requestExtensionReadyProbe() {
            window.postMessage({ type: "CHECK_EXTENSION_READY" }, "*");
        },
        async waitForExtensionReady(timeoutMs = 12000) {
            const started = Date.now();
            this.listenToExtension();
            this.requestExtensionReadyProbe();
            while (Date.now() - started < timeoutMs) {
                const localWorkerId = localStorage.getItem('local_worker_id');
                if (this.isExtConnected && localWorkerId) {
                    return { ok: true, workerId: localWorkerId };
                }
                await new Promise(r => setTimeout(r, 800));
                this.requestExtensionReadyProbe();
            }
            return {
                ok: false,
                workerId: localStorage.getItem('local_worker_id') || '',
            };
        },
        async waitForExtensionHeartbeat(workerId, timeoutMs = 12000) {
            const started = Date.now();
            while (Date.now() - started < timeoutMs) {
                try {
                    const checkRes = await this.authFetch(`/api/ext/check_node?worker_id=${encodeURIComponent(workerId)}`);
                    const checkData = await checkRes.json();
                    if (checkData.online) {
                        return { ok: true, data: checkData };
                    }
                } catch (e) {}
                await new Promise(r => setTimeout(r, 1200));
                this.syncTokenToExtension();
            }
            return { ok: false };
        },
        listenToExtension() {
            if (this.config?.reg_mode !== 'extension') return;
            if (this._hasExtensionListener) {
                this.syncTokenToExtension();
                return;
            }

            this._hasExtensionListener = true;
            this.isExtConnected = false;

            window.addEventListener("message", async (event) => {
                if (!event.data) return;

                if (event.data.type === "WORKER_READY") {
                    const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false });
                    if (this._extDetectionTimer) {
                        clearInterval(this._extDetectionTimer);
                        this._extDetectionTimer = null;
                    }

                    this.isExtConnected = true;
                    let localWorkerId = localStorage.getItem('local_worker_id');
                    if (!localWorkerId) {
                        localWorkerId = 'Node-' + Math.random().toString(36).substring(2, 6).toUpperCase();
                        localStorage.setItem('local_worker_id', localWorkerId);
                    }

                    this.logs.push({
                        parsed: true,
                        time: timeStr,
                        level: '总控',
                        text: `✅ 浏览器插件已连接，节点识别码: ${localWorkerId}`,
                        raw: `[${timeStr}] [总控] ✅ 浏览器插件已连接，节点识别码: ${localWorkerId}`
                    });
                    this.$nextTick(() => {
                        const container = document.getElementById('terminal-container');
                        if (container) container.scrollTop = container.scrollHeight;
                    });
                    this.syncTokenToExtension();
                    return;
                }

                if (event.data.type === "WORKER_LOG_REPLY") {
                    const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false });
                    this.logs.push({
                        parsed: true,
                        time: timeStr,
                        level: '节点',
                        text: event.data.log,
                        raw: `[${timeStr}] [节点] ${event.data.log}`
                    });
                    this.$nextTick(() => {
                        const container = document.getElementById('terminal-container');
                        if (container) container.scrollTop = container.scrollHeight;
                    });
                    return;
                }

                if (event.data.type === "WORKER_RESULT_REPLY") {
                    const result = event.data.result;
                    try {
                        await this.authFetch('/api/ext/submit_result', {
                            method: 'POST',
                            body: JSON.stringify(result)
                        });
                    } catch (e) {
                        console.error("古法统计上报失败", e);
                    }

                    if (result.status === 'success') {
                        this.showToast(`🎉 收到古法节点捷报！注册成功！`, "success");
                    } else {
                        this.showToast(`❌ 古法节点汇报失败: ${result.error_msg}`, "error");
                    }

                    if (this.isRunning) {
                        const targetCount = this.config?.normal_mode?.target_count || 0;
                        if (targetCount > 0 && this.stats && this.stats.success >= targetCount) {
                            this.showToast(`🎯 已达到目标产出数量 (${targetCount})，自动停止古法调度！`, "success");
                            await this.stopExtensionTask(false);
                            const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false });
                            this.logs.push({
                                parsed: true,
                                time: timeStr,
                                level: '总控',
                                text: `🛑 古法目标产量已达成，总控引擎已自动挂起。`,
                                raw: `[${timeStr}] [总控] 🛑 古法目标产量已达成，总控引擎已自动挂起。`
                            });
                            return;
                        }

                        this.showToast(`准备下发下一个古法插件任务...`, "info");
                        this._extDispatchTimer = setTimeout(() => {
                            this._extDispatchTimer = null;
                            this.dispatchExtensionTask();
                        }, 4000);
                    }
                }
            });

            if (this._extDetectionTimer) clearInterval(this._extDetectionTimer);
            this._extDetectionTimer = setInterval(() => {
                if (this.config?.reg_mode === 'extension' && !this.isExtConnected) {
                    window.postMessage({ type: "CHECK_EXTENSION_READY" }, "*");
                } else if (this.config?.reg_mode !== 'extension') {
                    clearInterval(this._extDetectionTimer);
                    this._extDetectionTimer = null;
                }
            }, 2000);
        },
        async changeRegMode(mode) {
            if (!this.config) return;
            if (mode === this.config.reg_mode) return;
            this.config.reg_mode = mode;
            await this.saveConfig();
            this.showToast(`模式已切换为: ${mode === 'protocol' ? '纯协议模式' : '古法插件模式'}`, 'info');

            if (mode === 'extension') {
                this.listenToExtension();
            } else {
                if (this._extDetectionTimer) {
                    clearInterval(this._extDetectionTimer);
                    this._extDetectionTimer = null;
                }
                this.isExtConnected = false;
                window.postMessage({ type: "CMD_STOP_WORKER" }, "*");
                await this.authFetch('/api/ext/stop', { method: 'POST' }).catch(() => {});
            }
        },
        async startExtensionTask() {
            if (this.config?.cpa_mode?.enable || this.config?.sub2api_mode?.enable) {
                this.showToast("古法插件模式当前仅支持常规量产模式，请先关闭 CPA / Sub2API 仓管。", "warning");
                return;
            }
            this.showToast("📡 正在探测插件节点在线状态...", "info");
            const extReady = await this.waitForExtensionReady(15000);
            if (!extReady.ok) {
                const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false });
                this.showToast("🚫 启动失败：浏览器插件未连接。", "error");
                this.logs.push({
                    parsed: true,
                    time: timeStr,
                    level: '系统',
                    text: '🛑 浏览器页面尚未收到 WORKER_READY。请先解压 plugin/openai-cpa-plugin.zip，并在浏览器扩展页开启开发者模式后加载解压后的文件夹，然后强制刷新当前页面，等待顶部出现“浏览器插件已连接”。',
                    raw: `[${timeStr}] [系统] 🛑 浏览器页面尚未收到 WORKER_READY。请先解压 plugin/openai-cpa-plugin.zip，并在浏览器扩展页开启开发者模式后加载解压后的文件夹，然后强制刷新当前页面，等待顶部出现“浏览器插件已连接”。`
                });
                return;
            }
            this.syncTokenToExtension();
            try {
                const localId = extReady.workerId;
                const heartbeat = await this.waitForExtensionHeartbeat(localId, 12000);
                if (!heartbeat.ok) {
                    const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false });
                    this.showToast(`🚫 启动失败：插件节点 [${localId}] 未连接或已掉线！`, "error");
                    this.logs.push({
                        parsed: true,
                        time: timeStr,
                        level: '系统',
                        text: `🛑 浏览器插件已回报 READY，但节点 [${localId}] 心跳未注册成功。请保持页面停留在本站几秒后再试，或重新刷新当前页面。`,
                        raw: `[${timeStr}] [系统] 🛑 浏览器插件已回报 READY，但节点 [${localId}] 心跳未注册成功。请保持页面停留在本站几秒后再试，或重新刷新当前页面。`
                    });
                    return;
                }
            } catch (e) {
                this.showToast("🚫 无法连接到后端检查插件节点状态", "error");
                return;
            }

            this.isRunning = true;
            this.currentTab = 'console';
            await this.authFetch('/api/ext/reset_stats', { method: 'POST' }).catch(() => {});
            this.pollStats();
            this.showToast("✅ 插件节点在线，已启动【古法插件模式】", "success");
            await this.dispatchExtensionTask();
        },
        async stopExtensionTask(showToast = true) {
            this.isRunning = false;
            if (this._extDispatchTimer) {
                clearTimeout(this._extDispatchTimer);
                this._extDispatchTimer = null;
            }
            window.postMessage({ type: "CMD_STOP_WORKER" }, "*");
            await this.authFetch('/api/ext/stop', { method: 'POST' }).catch(() => {});
            if (showToast) {
                this.showToast("已向古法插件发送停止指令", "info");
            }
            const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false });
            this.logs.push({
                parsed: true,
                time: timeStr,
                level: '系统',
                text: '🛑 已向浏览器插件发送停止指令，等待节点清场。',
                raw: `[${timeStr}] [系统] 🛑 已向浏览器插件发送停止指令，等待节点清场。`
            });
        },

		async toggleSystem() {
			if (this.config?.reg_mode === 'extension') {
                if (this.isRunning) await this.stopExtensionTask();
                else await this.startExtensionTask();
                return;
            }
            if (this.isRunning) {
                await this.stopTask();
            } else {
                let mode = 'normal';
                if (this.config?.cpa_mode?.enable) mode = 'cpa';
                if (this.config?.sub2api_mode?.enable) mode = 'sub2api';
                await this.startTask(mode);
            }
		},
        async startTask(mode) {
            try {
                const res = await this.authFetch(`/api/start?mode=${mode}`, { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success') {
                    this.isRunning = true;
                    this.currentTab = 'console';
                    this.pollStats();
                    this.showToast(`启动成功`, "success");
                } else { this.showToast(data.message, "error"); }
            } catch (e) { this.showToast("启动请求发送失败", "error"); }
        },
        async stopTask() {
            try {
                const res = await this.authFetch('/api/stop', { method: 'POST' });
                const data = await res.json();
                this.showToast("任务已停止", "info");
                this.isRunning = false;
                const now = new Date();
                const timeStr = now.toLocaleTimeString('zh-CN', { hour12: false }); // 获取如 14:30:05 格式
                this.logs.push({
                    parsed: true,
                    time: timeStr,
                    level: '系统',
                    text: '🛑 接收到紧急停止指令，引擎已停止运行！',
                    raw: `[${timeStr}] [系统] 🛑 接收到紧急停止指令，引擎已停止运行！`
                });

                this.$nextTick(() => {
                    const container = document.getElementById('terminal-container');
                    if (container) {
                        container.scrollTop = container.scrollHeight;
                    }
                });
                this.pollStats();
            } catch (e) {
                this.showToast("停止请求发送失败", "error");
            }
        },
        async bulkPushCPA() {
            if (!this.config.cpa_mode.enable) {
                this.showToast("🚫 请先开启 CPA 巡检并填写 API", "warning"); return;
            }
            if (this.selectedAccounts.length === 0) return;
            const confirmed = await this.customConfirm(`确定推送到 CPA？`);
            if (!confirmed) return;
            this.currentTab = 'console';
            for (let i = 0; i < this.selectedAccounts.length; i++) {
                const acc = this.selectedAccounts[i];
                try {
                    await this.authFetch('/api/account/action', {
                        method: 'POST', body: JSON.stringify({ email: acc.email, action: 'push' })
                    });
                } catch (e) {}
                await new Promise(r => setTimeout(r, 500));
            }
            this.showToast(`批量推送完毕！`, "success");
            this.selectedAccounts = []; 
        },
		async bulkPushSub2API() {
            if (!this.config.sub2api_mode.enable) {
                this.showToast("🚫 请先开启 Sub2API 模式并填写参数", "warning"); return;
            }
            if (this.selectedAccounts.length === 0) return;
            const confirmed = await this.customConfirm(`确定推送到 Sub2API？`);
            if (!confirmed) return;
            this.currentTab = 'console';
            for (let i = 0; i < this.selectedAccounts.length; i++) {
                const acc = this.selectedAccounts[i];
                try {
                    await this.authFetch('/api/account/action', {
                        method: 'POST', body: JSON.stringify({ email: acc.email, action: 'push_sub2api' })
                    });
                } catch (e) {}
                await new Promise(r => setTimeout(r, 500));
            }
            this.showToast(`批量推送完毕！`, "success");
            this.selectedAccounts = []; 
        },
        async triggerAccountAction(account, action) {
            if (action === 'push' && !this.config.cpa_mode.enable) {
                this.showToast("🚫 无法推送：请先配置 CPA 参数！", "warning"); return;
            }
            this.currentTab = 'console';
            try {
                const res = await this.authFetch('/api/account/action', {
                    method: 'POST', body: JSON.stringify({ email: account.email, action: action })
                });
                const result = await res.json();
                this.showToast(result.message, result.status);
            } catch (e) {}
        },
        async clearLogs() {
            this.logs = [];
            this.logBuffer = [];
            try { await this.authFetch('/api/logs/clear', { method: 'POST' }); } catch (e) {}
        },
		initSSE() {
            if (this.evtSource) {
                this.evtSource.close();
                this.evtSource = null;
            }
            if (this.logFlushTimer) {
                clearInterval(this.logFlushTimer);
                this.logFlushTimer = null;
            }
            if (this.sseReconnectTimer) {
                clearTimeout(this.sseReconnectTimer);
                this.sseReconnectTimer = null;
            }

            const token = localStorage.getItem('auth_token');
            if (!token) {
                this.logStreamStatus = '未登录';
                return;
            }
            const timestamp = new Date().getTime();
            const url = `/api/logs/stream?token=${token}&_t=${timestamp}`;

            this.logStreamStatus = '连接中';
            this.evtSource = new EventSource(url);
            this.evtSource.onopen = () => {
                this.logStreamStatus = '已连接';
                this.logStreamLastError = '';
            };
            this.logFlushTimer = setInterval(() => {
                if (this.logBuffer.length > 0) {
                    const container = document.getElementById('terminal-container');
                    let isScrolledToBottom = true;
                    if (container) {
                        isScrolledToBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 100;
                    }
                    this.logs.push(...this.logBuffer);
                    this.logBuffer = [];

                    if (this.logs.length > 500) {
                        this.logs.splice(0, this.logs.length - 500);
                    }
                    this.$nextTick(() => {
                        if (container && (isScrolledToBottom || this.logs.length < 20)) {
                            container.scrollTo({
                                top: container.scrollHeight,
                                behavior: 'auto'
                            });
                        }
                    });
                }
            }, 300);

            this.evtSource.onmessage = (event) => {
                let rawText = event.data;
                rawText = rawText.trim();
                if (!rawText) return;

                let logObj = { id: Date.now() + Math.random(), parsed: false, raw: rawText };
                const regex = /^\[(.*?)\]\s*\[(.*?)\]\s+(.*)$/;
                const match = rawText.match(regex);

                if (match) {
                    logObj = {
                        parsed: true,
                        time: match[1],
                        level: match[2].toUpperCase(),
                        text: match[3],
                        raw: rawText
                    };
                }
                this.logBuffer.push(logObj);
            };
            this.evtSource.onerror = (event) => {
                console.error("🔴 SSE 连接断开或异常。");
                this.logStreamStatus = '重连中';
                this.logStreamLastError = '日志通道中断，正在自动重连';
                if (this.evtSource) {
                    this.evtSource.close();
                    this.evtSource = null;
                }

                if (this.isLoggedIn) {
                    console.log("⏳ 准备在 3 秒后强制重新建立日志通道...");
                    this.sseReconnectTimer = setTimeout(() => {
                        this.initSSE();
                    }, 3000);
                }
            };
        },
		handleSubDomainToggle() {
			if (this.config.enable_sub_domains) {
				this.subDomainModal.email = this.config.cf_api_email || '';
				this.subDomainModal.key = this.config.cf_api_key || '';
				this.subDomainModal.show = true;
			}
		},
		// async executeGenerateDomainsOnly() {
			// if (!this.config.mail_domains) return this.showToast('请先填写上方的主发信域名池！', 'warning');
			
			// const level = this.config.sub_domain_level || 1;

			// try {
				// const res = await this.authFetch('/api/config/generate_subdomains', {
					// method: 'POST',
					// body: JSON.stringify({
						// main_domains: this.config.mail_domains,
						// count: this.config.sub_domain_count || 10,
						// level: level,
						// api_email: this.config.cf_api_email || '',
						// api_key: this.config.cf_api_key || '',
						// sync: false
					// })
				// });
				// const data = await res.json();
				// if (data.status === 'success') {
					// this.config.sub_domains_list = data.domains;
					// this.showToast('生成成功！如需推送到 CF，请点击右侧推送按钮。', 'success');
				// } else {
					// this.showToast(data.message, 'error');
				// }
			// } catch (e) {
				// this.showToast('生成接口请求失败', 'error');
			// }
		// },

		async executeSyncToCF() {
			const rawList = this.config.mail_domains || '';
			const subDomains = rawList.split(',').map(d => d.trim()).filter(d => d);
			
			if (subDomains.length === 0) return this.showToast('当前没有可解析的主域，请先填写！', 'warning');
			if (!this.config.cf_api_email || !this.config.cf_api_key) return this.showToast('请填写 CF 账号邮箱和 API Key！', 'warning');
			const confirmed = await this.customConfirm(`把 ${subDomains.length} 个主域名解析到 Cloudflare，确定继续吗？`);
			if (!confirmed) return;
			this.isLoadingSync = true;
			this.showToast('🚀 多线程同步中，请耐心等待...', 'info');
            this.currentTab = 'console';
			try {
				const res = await this.authFetch('/api/config/add_wildcard_dns', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						sub_domains: subDomains.join(','),
						api_email: this.config.cf_api_email,
						api_key: this.config.cf_api_key
					})
				});
				
				const data = await res.json();
				if (data.status === 'success') {
					this.showToast('✅ 解析成功...', 'success');
				} else {
					this.showToast(data.message || '解析失败', 'error');
				}
			} catch (e) {
				this.showToast('解析接口请求异常', 'error');
			} finally {
				this.isLoadingSync = false; 
			}
		},
		// async checkCfGlobalStatus() {
			// if (!this.config.mail_domains) return;
			// const domains = this.config.mail_domains;
			// try {
				// const res = await this.authFetch(`/api/config/cf_global_status?main_domain=${encodeURIComponent(domains)}`);
				// const data = await res.json();
				// if (data.status === 'success') {
					// this.cfGlobalStatusList = data.data; 
					// const allEnabled = data.data.length > 0 && data.data.every(item => item.is_enabled);
					// if (allEnabled && this.cfStatusTimer) {
						// this.stopCfStatusPolling(); 
						// this.showToast('✨ 线上状态已全部激活！', 'success');
					// }
				// }
			// } catch (e) {
				// this.showToast("无法获取 CF 路由全局状态", e);
			// }
		// },
		// async startCfStatusPolling() {
			// this.stopCfStatusPolling(); 
			// this.isLoadingCfRoutes = true;
			
			// this.showToast("🚀 开启 CF 状态智能监控...");

			// this.cfStatusTimer = setInterval(() => {
				// this.checkCfGlobalStatus();
			// }, 8000);
			// await this.fetchCfRoutes(); 
		// },
		// stopCfStatusPolling() {
			// if (this.cfStatusTimer) {
				// clearInterval(this.cfStatusTimer);
				// this.cfStatusTimer = null;
				// this.isLoadingCfRoutes = false;
				// this.showToast("🛑 智能监控已停止。");
			// }
		// },
		// async fetchCfRoutes() {
			// if (!this.config.mail_domains) return this.showToast('请先填写主发信域名池 (用于反推Zone ID)！', 'warning');
			// if (!this.config.cf_api_email || !this.config.cf_api_key) return this.showToast('请填写 CF 账号邮箱和 API Key！', 'warning');

			// this.isLoadingCfRoutes = true;
			// this.showToast('🔍 正在连线 Cloudflare 查询线上路由记录...', 'info');

			// try {
				// const res = await this.authFetch('/api/config/query_cf_domains', {
					// method: 'POST',
					// body: JSON.stringify({
						// main_domains: this.config.mail_domains,
						// api_email: this.config.cf_api_email,
						// api_key: this.config.cf_api_key
					// })
				// });
				// const data = await res.json();
				// if (data.status === 'success') {
					// if (data.domains) {
						// this.cfRoutes = data.domains.split(',').filter(d=>d).map(d => ({ 
							// domain: d, 
							// loading: false
						// }));
					// } else {
						// this.cfRoutes = [];
					// }
					// this.selectedCfRoutes = [];
					// this.showToast(data.message, 'success');
				// } else {
					// this.showToast(data.message, 'error');
				// }
				// await this.checkCfGlobalStatus();
			// } catch (e) {
				// this.showToast('查询接口请求失败', 'error');
			// } finally {
				// if (!this.cfStatusTimer) {
					// this.isLoadingCfRoutes = false;
				// }
			// }
		// },

		// async deleteSelectedCfRoutes() {
			// if (this.selectedCfRoutes.length === 0) return;
			// const domainsToDelete = this.selectedCfRoutes.map(item => item.domain);
			
			// this.isDeletingCfRoutes = true;
			// try {
				// await this.executeDeleteCfDomains(domainsToDelete);
			// } finally {
				// this.isDeletingCfRoutes = false;
			// }
		// },

		// async deleteSingleCfRoute(routeObj) {
			// routeObj.loading = true; 
			// try {
				// await this.executeDeleteCfDomains([routeObj.domain]);
			// } finally {
				// routeObj.loading = false;
			// }
		// },

		// async executeDeleteCfDomains(domainsArray) {
			// if (!this.config.cf_api_email || !this.config.cf_api_key) return this.showToast('请填写 CF 账号邮箱和 API Key！', 'warning');

			// const count = domainsArray.length;
			// const confirmed = await this.customConfirm(`⚠️ 危险操作：\n\n即将调用 Cloudflare API 强制删除这 ${count} 个域名的路由解析记录。确定要继续吗？`);
			// if (!confirmed) return;
			// if (count > 1) this.isDeletingCfRoutes = true;
			// this.showToast(`🗑️ 正在连线 Cloudflare 销毁 ${count} 条记录...`, 'info');

			// try {
				// const res = await this.authFetch('/api/config/delete_cf_domains', {
					// method: 'POST',
					// body: JSON.stringify({
						// sub_domains: domainsArray.join(','),
						// api_email: this.config.cf_api_email,
						// api_key: this.config.cf_api_key
					// })
				// });
				// const data = await res.json();
				// if (data.status === 'success') {
					// this.showToast(data.message, 'success');
					// this.fetchCfRoutes();
				// } else {
					// this.showToast(data.message, 'error');
				// }
			// } catch (e) {
				// this.showToast('删除接口请求失败', 'error');
			// } finally {
				// this.isDeletingCfRoutes = false;
			// }
		// },

		toggleAllCfRoutes(event) {
			if (event.target.checked) this.selectedCfRoutes = [...this.cfRoutes];
			else this.selectedCfRoutes = [];
		},
        async fetchHeroSmsBalance() {
            if (!this.config.hero_sms.api_key) return this.showToast('请先填写 API Key！', 'warning');
            this.isLoadingBalance = true;
            try {
                const res = await this.authFetch('/api/sms/balance'); // 需后端配合增加此接口
                const data = await res.json();
                if (data.status === 'success') {
                    this.heroSmsBalance = data.balance;
                    this.showToast('余额刷新成功', 'success');
                } else {
                    this.showToast(data.message || '查询失败', 'error');
                }
            } catch (e) {
                this.showToast('查询异常: ' + e.message, 'error');
            } finally {
                this.isLoadingBalance = false;
            }
        },
        async fetchHeroSmsPrices() {
            if (!this.config.hero_sms.api_key) return this.showToast('请先填写 API Key！', 'warning');
            this.isLoadingPrices = true;
            try {
                const res = await this.authFetch('/api/sms/prices', {
                    method: 'POST',
                    body: JSON.stringify({ service: this.config.hero_sms.service })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.heroSmsPrices = data.prices;
                    this.showToast(`获取到 ${data.prices.length} 个国家的库存数据`, 'success');
                } else {
                    this.showToast(data.message || '获取失败', 'error');
                }
            } catch (e) {
                this.showToast('通信异常: ' + e.message, 'error');
            } finally {
                this.isLoadingPrices = false;
            }
        },
        async executeManualLuckMailBuy() {
            if (this.luckmailManualQty < 1) return;
            this.isManualBuying = true;
            try {
                const res = await this.authFetch('/api/luckmail/bulk_buy', {
                    method: 'POST',
                    body: JSON.stringify({
                        quantity: this.luckmailManualQty,
                        auto_tag: this.luckmailManualAutoTag,
                        config: this.config.luckmail
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.showToast(data.message, 'success');
                } else {
                    this.showToast('购买失败: ' + data.message, 'error');
                }
            } catch (e) {
                this.showToast('网络请求异常', 'error');
            } finally {
                this.isManualBuying = false;
            }
        },
        async fetchSub2ApiGroups() {
            if (!this.config || !this.config.sub2api_mode) return;
            if (!this.config.sub2api_mode.api_url || !this.config.sub2api_mode.api_key) {
                this.showToast('Please save the Sub2API URL and API key first.', 'warning');
                return;
            }

            this.isLoadingSub2APIGroups = true;
            try {
                const res = await this.authFetch('/api/sub2api/groups');
                const data = await res.json();
                if (data.status === 'success') {
                    const raw = data.data;
                    let groups = [];
                    if (Array.isArray(raw)) groups = raw;
                    else if (raw && Array.isArray(raw.list)) groups = raw.list;
                    else if (raw && Array.isArray(raw.data)) groups = raw.data;

                    this.sub2apiGroups = groups;
                    if (groups.length === 0) {
                        this.showToast('No Sub2API groups found. Create one in Sub2API first.', 'warning');
                    } else {
                        this.showToast(`Fetched ${groups.length} Sub2API groups.`, 'success');
                    }
                } else {
                    this.showToast(data.message || 'Failed to fetch Sub2API groups.', 'error');
                }
            } catch (e) {
                this.showToast('Group fetch error: ' + e.message, 'error');
            } finally {
                this.isLoadingSub2APIGroups = false;
            }
        },
        isGroupSelected(id) {
            if (!this.config || !this.config.sub2api_mode) return false;
            const ids = String(this.config.sub2api_mode.account_group_ids || '')
                .split(',')
                .map(s => s.trim())
                .filter(s => s);
            return ids.includes(String(id));
        },
        toggleGroup(id) {
            if (!this.config || !this.config.sub2api_mode) return;
            const ids = String(this.config.sub2api_mode.account_group_ids || '')
                .split(',')
                .map(s => s.trim())
                .filter(s => s);
            const value = String(id);
            const index = ids.indexOf(value);
            if (index >= 0) ids.splice(index, 1);
            else ids.push(value);
            this.config.sub2api_mode.account_group_ids = ids.join(',');
        },
        async startManualCheck() {
            if(this.isRunning) {
                this.showToast('请先停止当前运行的任务', 'warning');
                return;
            }
            try {
                const res = await this.authFetch('/api/start_check', {
                    method: 'POST'
                });
                const data = await res.json();

                if(data.code === 200) {
                    this.showToast(data.message, 'success');
                    this.pollStats();
                } else {
                    this.showToast(data.message || '启动测活失败', 'error');
                }
            } catch (err) {
                this.showToast('网络请求异常', 'error');
            }
        },
        async checkUpdate(isManual = false) {
            try {
                const res = await this.authFetch(`/api/system/check_update?current_version=${this.appVersion}`);
                const data = await res.json();
                const downloadUrl = data.download_url || '';
                const versionPageUrl = data.version_page_url || data.html_url || this.versionPageUrl;

                if (data.status === 'success') {
                    this.versionPageUrl = versionPageUrl;
                    if (data.has_update) {
                        this.updateInfo = {
                            hasUpdate: true,
                            version: data.remote_version,
                            url: downloadUrl,
                            changelog: data.changelog
                        };
                        if (isManual) {
                            await this.promptUpdate();
                        }
                    } else if (isManual) {
                        this.updateInfo = { hasUpdate: false, version: '', url: '', changelog: '' };
                        this.showToast(`当前已是最新版本：${this.appVersion}`, 'success');
                    }
                } else {
                    if (isManual) this.showToast(`${data.message || "检查更新失败"}。可点击左上角版本号查看线上版本页。`, "error");
                    this.versionPageUrl = versionPageUrl;
                }
            } catch (e) {
                if (isManual) this.showToast("检查更新请求失败，请检查网络。可点击左上角版本号查看线上版本页。", "error");
            }
        },
        async promptUpdate() {
            if (!this.updateInfo.hasUpdate) return;
            const msg = `🚀 发现新版本: ${this.updateInfo.version}\n\n📝 更新信息:\n${this.updateInfo.changelog}\n\n是否下载到当前软件目录下的 updates/${this.updateInfo.version} 并自动解压？`;
            const confirmed = await this.customConfirm(msg);
            if (confirmed) {
                await this.triggerUpdateDownload(this.updateInfo.url, this.updateInfo.version);
                await this.fetchUpdatePackages(false);
            }
        },
        async fetchUpdatePackages(showSuccess = false) {
            this.isUpdatePackagesLoading = true;
            try {
                const res = await this.authFetch('/api/system/update_packages');
                const data = await res.json();
                if (data.status === 'success') {
                    this.updatePackages = Array.isArray(data.data?.packages) ? data.data.packages : [];
                    if (showSuccess) {
                        this.showToast(data.message || '本地更新包列表已刷新', 'success');
                    }
                } else if (showSuccess) {
                    this.showToast(data.message || '读取本地更新包列表失败', 'error');
                }
                return data;
            } catch (e) {
                if (showSuccess) {
                    this.showToast('读取本地更新包列表失败', 'error');
                }
                return { status: 'error', message: '读取本地更新包列表失败' };
            } finally {
                this.isUpdatePackagesLoading = false;
            }
        },
        async loadUpdateCenterData(showSuccess = false) {
            await this.checkUpdate(false);
            await this.inspectProjectUpdate(false);
            await this.fetchUpdatePackages(showSuccess);
        },
        async inspectProjectUpdate(showSuccess = false) {
            this.isProjectUpdateChecking = true;
            try {
                const res = await this.authFetch('/api/system/project_update_status');
                const data = await res.json();
                this.projectUpdateStatus = data.data || null;
                if (showSuccess) {
                    const level = data.status === 'success' ? 'success' : (data.status === 'warning' ? 'warning' : 'error');
                    this.showToast(data.message || '项目更新状态已读取', level);
                }
                return data;
            } catch (e) {
                if (showSuccess) {
                    this.showToast('读取项目更新状态失败', 'error');
                }
                return { status: 'error', message: '读取项目更新状态失败' };
            } finally {
                this.isProjectUpdateChecking = false;
            }
        },
        async updateCurrentProject() {
            if (this.isRunning) {
                this.showToast('请先停止当前运行的任务', 'warning');
                return;
            }
            const inspect = await this.inspectProjectUpdate(false);
            if (inspect.status !== 'success') {
                this.showToast(inspect.message || '当前不满足项目内更新条件', inspect.status === 'warning' ? 'warning' : 'error');
                return;
            }
            const current = inspect.data || {};
            const summary = [
                `当前分支：${current.branch || '未知'}`,
                `本地提交：${(current.local_head || '').slice(0, 7) || '未知'}`,
                `远端提交：${(current.remote_head || '').slice(0, 7) || '未知'}`,
                '',
                '满足 fast-forward 更新条件，是否立即更新当前项目并自动重启？'
            ].join('\n');
            const confirmed = await this.customConfirm(summary);
            if (!confirmed) return;

            this.isProjectUpdating = true;
            try {
                this.showToast('正在执行 git fast-forward 更新...', 'info');
                const res = await this.authFetch('/api/system/update_project', {
                    method: 'POST',
                    body: JSON.stringify({ restart_after_update: true })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.showToast(data.message || '当前项目已更新，系统即将重启...', 'success');
                    if (this.statsTimer) clearInterval(this.statsTimer);
                    if (this.evtSource) this.evtSource.close();
                    setTimeout(() => {
                        window.location.reload();
                    }, 8000);
                } else {
                    const level = data.status === 'warning' ? 'warning' : 'error';
                    this.showToast(data.message || '当前项目更新失败', level);
                }
            } catch (e) {
                this.showToast('当前项目更新失败，请检查后端日志', 'error');
            } finally {
                this.isProjectUpdating = false;
            }
        },
        async migrateUpdatePackage(pkg) {
            if (!pkg?.version) return;
            if (this.isRunning) {
                this.showToast('请先停止当前运行的任务', 'warning');
                return;
            }
            const summary = [
                `目标版本：${pkg.version}`,
                `解压目录：${pkg.extract_dir || '未知'}`,
                '',
                '将把当前项目的 data 目录复制到该版本目录下。',
                '会自动删除当前版本 zip 包，并清理其他旧 updates 缓存。',
                '',
                '确定继续吗？'
            ].join('\n');
            const confirmed = await this.customConfirm(summary);
            if (!confirmed) return;

            this.migratingUpdateVersion = pkg.version;
            try {
                const res = await this.authFetch('/api/system/migrate_update_package', {
                    method: 'POST',
                    body: JSON.stringify({
                        version: pkg.version,
                        cleanup_zip: true,
                        cleanup_other_versions: true
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const copiedFiles = data.data?.copied_files ?? 0;
                    const removedCount = Array.isArray(data.data?.removed_paths) ? data.data.removed_paths.length : 0;
                    this.showToast(`迁移完成：复制 ${copiedFiles} 个文件，清理 ${removedCount} 个缓存路径`, 'success');
                    await this.fetchUpdatePackages(false);
                } else {
                    this.showToast(data.message || '迁移更新包配置失败', data.status === 'warning' ? 'warning' : 'error');
                }
            } catch (e) {
                this.showToast('迁移更新包配置失败，请检查后端日志', 'error');
            } finally {
                this.migratingUpdateVersion = '';
            }
        },
        async getGmailAuthUrl() {
            this.gmailOAuth.isGenerating = true;
            try {
                const res = await this.authFetch('/api/gmail/auth_url');
                const data = await res.json();
                if (data.status === 'success') {
                    this.gmailOAuth.authUrl = data.url;
                    this.showToast("授权链接已生成，请在浏览器中打开", "success");
                } else {
                    this.showToast(data.message, "error");
                }
            } catch (e) {
                this.showToast("获取失败，请检查 credentials.json 是否已放置", "error");
            } finally {
                this.gmailOAuth.isGenerating = false;
            }
        },
        async submitGmailAuthCode() {
            this.gmailOAuth.isLoading = true;
            try {
                const res = await this.authFetch('/api/gmail/exchange_code', {
                    method: 'POST',
                    body: JSON.stringify({ code: this.gmailOAuth.pastedCode })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.showToast("🎉 永久授权成功！系统已自动关联该 Gmail", "success");
                    this.gmailOAuth.authUrl = '';
                    this.gmailOAuth.pastedCode = '';
                } else {
                    this.showToast(data.message, "error");
                }
            } catch (e) {
                this.showToast("网络请求异常", "error");
            } finally {
                this.gmailOAuth.isLoading = false;
            }
        },
        async restartSystem() {
            const confirmed = await this.customConfirm("⚠️ 危险操作：\n\n确定要重启整个后端系统吗？\n如果当前有任务正在运行，将会被强制中断！");
            if (!confirmed) return;

            try {
                this.showToast("🚀 正在向服务器发送重启指令...", "info");
                const res = await this.authFetch('/api/system/restart', { method: 'POST' });
                const data = await res.json();

                if (data.status === 'success') {
                    this.showToast("✅ 系统正在重启，网页将于 6 秒后自动刷新...", "success");
                    if(this.statsTimer) clearInterval(this.statsTimer);
                    if(this.evtSource) this.evtSource.close();

                    setTimeout(() => {
                        window.location.reload();
                    }, 6000);
                } else {
                    this.showToast(data.message || "重启指令发送失败", "error");
                }
            } catch (e) {
                this.showToast("请求异常，请检查后端状态", "error");
            }
        },
        formatTime(dateStr) {
            if (!dateStr) return '-';
            let utcStr = dateStr;
            if (typeof dateStr === 'string' && !dateStr.includes('Z')) {
                utcStr = dateStr.replace(' ', 'T') + 'Z';
            }
            const d = new Date(utcStr);
            if (isNaN(d.getTime())) return dateStr;
            const pad = (n) => n.toString().padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        },
        async exportSub2Api() {
            if (this.selectedAccounts.length === 0) {
                this.showToast('请先勾选账号', 'warning');
                return;
            }
            try {
                const emailsToExport = this.selectedAccounts.map(item =>
                    typeof item === 'object' ? item.email : item
                );

                const response = await this.authFetch('/api/accounts/export_sub2api', {
                    method: 'POST',
                    body: JSON.stringify({ emails: emailsToExport })
                });
                const res = await response.json();

                if (res.status === 'success') {
                    const accounts = res.data.accounts;
                    const timestamp = Math.floor(Date.now() / 1000);

                    if (accounts.length > 1) {
                        const zip = new JSZip();

                        accounts.forEach((acc, index) => {
                            const prefix = (acc.name || "user").split('@')[0];

                            const singleAccountData = {
                                exported_at: res.data.exported_at,
                                proxies: res.data.proxies,
                                accounts: [acc]
                            };

                            const filename = `sub2api_${prefix}_${timestamp + index}.json`;
                            zip.file(filename, JSON.stringify(singleAccountData, null, 2));
                        });

                        const content = await zip.generateAsync({ type: "blob" });
                        const url = window.URL.createObjectURL(content);
                        const link = document.createElement('a');
                        link.href = url;
                        link.download = `Sub2Api_批量导出_${accounts.length}个_${timestamp}.zip`;
                        document.body.appendChild(link);
                        link.click();
                        link.remove();
                        window.URL.revokeObjectURL(url);

                        this.showToast(`🎉 成功打包并下载 ${accounts.length} 个独立配置文件！`, 'success');
                    } else {
                        const content = JSON.stringify(res.data, null, 2);
                        const blob = new Blob([content], { type: 'application/json' });
                        const url = window.URL.createObjectURL(blob);
                        const link = document.createElement('a');
                        link.href = url;
                        link.download = `sub2api_export_${timestamp}.json`;
                        document.body.appendChild(link);
                        link.click();
                        link.remove();
                        window.URL.revokeObjectURL(url);

                        this.showToast(`成功导出 ${accounts.length} 个账号到单个文件`, 'success');
                    }

                    this.selectedAccounts = [];
                } else {
                    this.showToast(res.message || '导出失败', 'error');
                }
            } catch (error) {
                console.error('导出异常:', error);
                this.showToast('导出异常，请检查 JSZip 是否加载', 'error');
            }
        },

        async fetchCloudAccounts() {
            if (this.cloudFilters.length === 0) {
                this.cloudAccounts = [];
                this.cloudTotal = 0;
                return;
            }
            const types = this.cloudFilters.join(',');
            try {
                const res = await this.authFetch(`/api/cloud/accounts?types=${types}&page=${this.cloudPage}&page_size=${this.cloudPageSize}`);
                const data = await res.json();
                if(data.status === 'success') {
                    this.cloudAccounts = (data.data || []).map(acc => ({
                        ...acc,
                        last_check: this.localCheckTimes[acc.id] || acc.last_check || '-',
                        details: this.localCloudDetails[acc.id] || acc.details || {},
                        _loading: null
                    }));
                    this.cloudTotal = data.total || 0;
                    this.selectedCloud = [];
                } else {
                    this.showToast(data.message, "error");
                }
            } catch (e) {
                console.error(e);
                this.showToast("获取云端数据失败", "error");
            }
        },

        async singleCloudAction(acc, action) {
            if (action === 'delete' && !confirm('⚠️ 危险操作：确认在远端彻底删除该账号吗？')) return;

            const actionName = action === 'check' ? '测活' : (action === 'enable' ? '启用' : (action === 'disable' ? '禁用' : '删除'));
            this.showToast(`正在对账号进行 ${actionName}，请稍候...`, 'info');
            acc._loading = action;

            try {
                const res = await this.authFetch('/api/cloud/action', {
                    method: 'POST',
                    body: JSON.stringify({ accounts: [{id: String(acc.id), type: acc.account_type}], action: action })
                });
                const result = await res.json();
                if (result.updated_details && result.updated_details[acc.id]) {
                    acc.details = result.updated_details[acc.id];
                    this.localCloudDetails[acc.id] = result.updated_details[acc.id];
                }
                if (action === 'enable' && result.status !== 'error') acc.status = 'active';
                if (action === 'disable' && result.status !== 'error') acc.status = 'disabled';

                if (action === 'check') {
                    const now = new Date().toLocaleString('zh-CN', { hour12: false });
                    this.localCheckTimes[acc.id] = now;
                    acc.last_check = now;

                    if (result.status === 'warning') {
                        acc.status = 'disabled';
                    }
                }
                this.showToast(result.message, result.status);

                setTimeout(() => {
                    if (action === 'delete' || action === 'check') {
                        this.fetchCloudAccounts();
                    }
                }, 1500);

            } catch (e) {
                this.showToast("操作异常，请检查网络", "error");
            } finally {
                acc._loading = null;
            }
        },

        async bulkCloudAction(action) {
            if (this.selectedCloud.length === 0) {
                return this.showToast('请先勾选需要操作的账号', 'warning');
            }
            if (action === 'delete' && !confirm(`⚠️ 危险操作：确认删除选中的 ${this.selectedCloud.length} 个账号吗？`)) return;

            const actionName = action === 'check' ? '测活' : (action === 'enable' ? '启用' : (action === 'disable' ? '禁用' : '删除'));
            this.showToast(`正在批量 ${actionName} ${this.selectedCloud.length} 个账号，耗时较长请耐心等待...`, 'info');
            this.isCloudActionLoading = true;

            try {
                const res = await this.authFetch('/api/cloud/action', {
                    method: 'POST',
                    body: JSON.stringify({ accounts: this.selectedCloud, action: action })
                });
                const result = await res.json();
                if (result.updated_details) {
                    this.selectedCloud.forEach(selected => {
                        const targetAcc = this.cloudAccounts.find(a => String(a.id) === String(selected.id) && a.account_type === selected.type);
                        if (result.updated_details) {
                            this.selectedCloud.forEach(selected => {
                                if (result.updated_details[selected.id]) {
                                    this.localCloudDetails[selected.id] = result.updated_details[selected.id]; // 存入缓存
                                }
                            });
                        }
                    });
                }
                if (action === 'check') {
                    const now = new Date().toLocaleString('zh-CN', { hour12: false });
                    this.selectedCloud.forEach(c => { this.localCheckTimes[c.id] = now; });
                }

                this.showToast(result.message, result.status);
                this.fetchCloudAccounts();
                this.selectedCloud = [];
            } catch (e) {
                this.showToast("批量操作异常", "error");
            } finally {
                this.isCloudActionLoading = false;
            }
        },
        toggleAllCloud(e) {
            if (e.target.checked) {
                this.selectedCloud = this.cloudAccounts.map(a => ({ id: String(a.id), type: a.account_type }));
            } else {
                this.selectedCloud = [];
            }
        },
        viewCloudDetails(acc) {
            if (!acc.details || Object.keys(acc.details).length === 0) {
                this.showToast("CPA 账号暂无用量缓存，请先点击【测活】拉取！", "warning");
                return;
            }
            this.currentCloudDetail = acc;
            this.showCloudDetailModal = true;
        },
        changeCloudPage(newPage) {
            if (newPage < 1 || newPage > this.cloudTotalPages) return;
            this.cloudPage = newPage;
            this.fetchCloudAccounts();
        },
        changeCloudPageSize() {
            this.cloudPage = 1;
            this.selectedCloud = [];
            this.fetchCloudAccounts();
        },
        async remoteControlNode(nodeName, action) {
            try {
                // 调用带验证的控制接口
                const res = await this.authFetch('/api/cluster/control', {
                    method: 'POST',
                    body: JSON.stringify({ node_name: nodeName, action: action })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.showToast(`✅ 指令 [${action}] 已成功发送至节点: ${nodeName}`, 'success'); //
                } else {
                    this.showToast(data.message, 'warning'); //
                }
            } catch (e) {
                this.showToast('控制请求异常', 'error'); //
            }
        },
        async toggleClusterNodeConnection(nodeName, allowConnect) {
            const action = allowConnect ? 'connect' : 'disconnect';
            try {
                const res = await this.authFetch('/api/cluster/control', {
                    method: 'POST',
                    body: JSON.stringify({ node_name: nodeName, action })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    this.showToast(allowConnect ? `已允许节点重新连接：${nodeName}` : `已断开节点连接：${nodeName}`, 'success');
                } else {
                    this.showToast(data.message || '连接状态切换失败', 'warning');
                }
            } catch (e) {
                this.showToast('连接状态切换异常', 'error');
            }
        },
        async fetchLocalClusterStatus(showToast = false) {
            if (!this.isLoggedIn) return;
            this.isLocalClusterStatusLoading = true;
            try {
                const res = await this.authFetch('/api/cluster/local_status');
                const data = await res.json();
                if (data.status === 'success') {
                    this.localClusterStatus = data.data || null;
                    if (showToast) {
                        this.showToast('已刷新本机子控连接状态', 'success');
                    }
                } else if (showToast) {
                    this.showToast(data.message || '读取本机子控状态失败', 'warning');
                }
            } catch (e) {
                if (showToast) {
                    this.showToast('读取本机子控状态失败', 'error');
                }
            } finally {
                this.isLocalClusterStatusLoading = false;
            }
        },
        async toggleLocalClusterLink() {
            if (!this.config) return;
            const nextEnabled = !(this.config.cluster_enabled !== false);
            const confirmed = await this.customConfirm(nextEnabled ? '确认恢复子控与主控的连接吗？恢复后会重新开始上报本机状态，但不会影响主任务运行。' : '确认断开子控与主控的连接吗？断开后主任务继续运行，只是不再向主控上报。');
            if (!confirmed) return;

            this.config.cluster_enabled = nextEnabled;
            await this.saveConfig(false);
            await this.fetchLocalClusterStatus(false);
            this.showToast(nextEnabled ? '已恢复子控连接' : '已断开子控连接', 'success');
        },
        formatDuration(seconds) {
            if (!seconds || seconds < 0) return "0s";
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = Math.floor(seconds % 60);

            let res = "";
            if (h > 0) res += h + "h ";
            if (m > 0 || h > 0) res += m + "m ";
            res += s + "s";
            return res;
        },
        getOnlineDuration(joinTime) {
            if (!joinTime) return '0s';
            const diff = this.nowTimestamp - Math.floor(joinTime);
            return this.formatDuration(diff);
        },
        maskValue(val, type = 'auto') {
            if (!val) return '未配置';
            if (type === 'email' || (type === 'auto' && val.includes('@'))) {
                const parts = val.split('@');
                return parts[0].substring(0, 2) + '***@' + '***';
            }
            if (type === 'url' || (type === 'auto' && val.startsWith('http'))) {
                try {
                    const url = new URL(val);
                    return `${url.protocol}//*****${url.port ? ':'+url.port : ''}${url.pathname.length > 1 ? '/...' : ''}`;
                } catch(e) { return val.substring(0, 8) + '...'; }
            }
            return val.length > 8 ? val.substring(0, 4) + '***' + val.slice(-4) : val.substring(0, 2) + '***';
        },
        initClusterWebSocket() {
            if (this.clusterWs) {
                this.clusterWs.close();
            }

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const token = localStorage.getItem('auth_token');
            const wsUrl = `${protocol}//${window.location.host}/api/cluster/view_ws?token=${token}`;

            this.clusterWs = new WebSocket(wsUrl);

            this.clusterWs.onerror = () => {
                if (this.clusterWs) {
                    this.clusterWs.close();
                }
            };

            this.clusterWs.onmessage = (event) => {
                const res = JSON.parse(event.data);
                if (res.status === 'success') {
                    this.clusterNodes = res.nodes;
                    this.syncClusterNodeSelection();
                }
            };

            this.clusterWs.onclose = () => {
                this.clusterWs = null;
            };
        },
    }
}).mount('#app');



