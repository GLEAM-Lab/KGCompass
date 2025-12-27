/**
 * KGCompass Web Interface - JavaScript Logic
 * 管理修复任务的前端交互和实时更新
 */

class KGCompassApp {
    constructor() {
        this.socket = null;
        this.currentTaskId = null;
        this.currentTask = null;
        this.logBuffer = [];
        this.isCustomMode = false;
        this.validatedRepoInfo = null;
        
        this.initializeApp();
    }

    /**
     * 初始化应用
     */
    initializeApp() {
        this.initializeSocket();
        this.setupEventListeners();
        this.setupExampleButtons();
        this.setupRepoSelector();
        
        console.log('🚀 KGCompass App initialized');
    }

    /**
     * 初始化 WebSocket 连接
     */
    initializeSocket() {
        this.socket = io();
        
        this.socket.on('connect', () => {
            console.log('✅ WebSocket connected');
            this.showNotification('已连接到服务器', 'success');
        });
        
        this.socket.on('disconnect', () => {
            console.log('❌ WebSocket disconnected');
            this.showNotification('与服务器断开连接', 'warning');
        });
        
        this.socket.on('connected', (data) => {
            console.log('📡 Server message:', data.message);
        });
        
        // 任务更新事件
        this.socket.on('task_update', (data) => {
            this.handleTaskUpdate(data);
        });
        
        // 任务日志事件
        this.socket.on('task_log', (data) => {
            this.handleTaskLog(data);
        });
        
        // 任务进度事件
        this.socket.on('task_progress', (data) => {
            this.handleTaskProgress(data);
        });
    }

    /**
     * 设置事件监听器
     */
    setupEventListeners() {
        // 修复表单提交
        const repairForm = document.getElementById('repairForm');
        repairForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.startRepairTask();
        });
        
        // 下载补丁按钮
        const downloadBtn = document.getElementById('downloadPatchBtn');
        downloadBtn.addEventListener('click', () => {
            this.downloadPatch();
        });
        
        // 查看报告按钮
        const viewReportBtn = document.getElementById('viewReportBtn');
        viewReportBtn.addEventListener('click', () => {
            this.viewReport();
        });
        
        // 新建任务按钮
        const newTaskBtn = document.getElementById('newTaskBtn');
        newTaskBtn.addEventListener('click', () => {
            this.resetInterface();
        });
        
        // 模式切换监听 - 使用 Bootstrap tab 事件
        const predefinedTab = document.getElementById('predefined-tab');
        const customTab = document.getElementById('custom-tab');
        
        // 监听 Bootstrap tab 显示事件
        predefinedTab.addEventListener('shown.bs.tab', () => {
            this.isCustomMode = false;
            this.validatedRepoInfo = null;
            console.log('切换到预定义模式');
        });
        
        customTab.addEventListener('shown.bs.tab', () => {
            this.isCustomMode = true;
            console.log('切换到自定义模式');
        });
        
        // 验证仓库按钮
        const validateRepoBtn = document.getElementById('validateRepoBtn');
        if (validateRepoBtn) {
            validateRepoBtn.addEventListener('click', () => {
                this.validateGitHubRepo();
            });
        }
        
        // GitHub URL 输入框失去焦点时自动验证
        const githubUrl = document.getElementById('githubUrl');
        if (githubUrl) {
            let validateTimeout;
            githubUrl.addEventListener('input', () => {
                clearTimeout(validateTimeout);
                validateTimeout = setTimeout(() => {
                    const url = githubUrl.value.trim();
                    if (url) {
                        this.validateGitHubRepo();
                    }
                }, 1000); // 1秒后自动验证
            });
        }
    }

    /**
     * 设置示例按钮
     */
    setupExampleButtons() {
        const exampleContainer = document.getElementById('exampleButtons');
        
        // 清空容器
        exampleContainer.innerHTML = '';
        
        // 为每个仓库创建示例按钮
        Object.keys(window.exampleIssues).forEach(repoKey => {
            const examples = window.exampleIssues[repoKey];
            if (examples && examples.length > 0) {
                // 只显示第一个示例，避免界面过于拥挤
                const issueNumber = examples[0];
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'btn btn-outline-secondary btn-sm example-btn';
                // 获取仓库的简短名称（取最后一部分）
                const repoShortName = repoKey.split('__')[1] || repoKey;
                button.textContent = `#${issueNumber} (${repoShortName})`;
                button.onclick = () => this.fillExample(repoKey, issueNumber);
                
                exampleContainer.appendChild(button);
            }
        });
    }

    /**
     * 设置仓库选择器
     */
    setupRepoSelector() {
        const repoSelect = document.getElementById('repoSelect');
        const repoDescription = document.getElementById('repoDescription');
        const repoPrefix = document.getElementById('repoPrefix');
        
        repoSelect.addEventListener('change', (e) => {
            const selectedRepo = e.target.value;
            const option = e.target.selectedOptions[0];
            
            if (selectedRepo && option) {
                const description = option.dataset.description;
                const stars = option.dataset.stars;
                repoDescription.textContent = `${description} (${stars} ⭐)`;
                
                // 更新前缀显示 - 只显示仓库简称
                const repoShortName = selectedRepo.split('__')[1] || selectedRepo;
                repoPrefix.textContent = `${repoShortName} Issue`;
                
                // 更新示例按钮
                this.updateExampleButtons(selectedRepo);
            } else {
                repoDescription.textContent = '';
                repoPrefix.textContent = 'Issue 编号';
                this.setupExampleButtons(); // 重置为所有示例
            }
        });
    }

    /**
     * 更新示例按钮（只显示选中仓库的示例）
     */
    updateExampleButtons(repoKey) {
        const exampleContainer = document.getElementById('exampleButtons');
        exampleContainer.innerHTML = '';
        
        const examples = window.exampleIssues[repoKey];
        if (examples && examples.length > 0) {
            examples.forEach(issueNumber => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'btn btn-outline-info btn-sm example-btn';
                button.textContent = `#${issueNumber}`;
                button.onclick = () => this.fillExample(repoKey, issueNumber);
                
                exampleContainer.appendChild(button);
            });
        }
    }

    /**
     * 填充示例数据
     */
    fillExample(repoKey, issueNumber) {
        document.getElementById('repoSelect').value = repoKey;
        document.getElementById('issueNumber').value = issueNumber;
        
        // 触发仓库选择器的 change 事件
        const repoSelect = document.getElementById('repoSelect');
        const event = new Event('change');
        repoSelect.dispatchEvent(event);
        
        this.showNotification(`已选择 Issue #${issueNumber}`, 'info');
    }

    /**
     * 验证 GitHub 仓库
     */
    async validateGitHubRepo() {
        const githubUrl = document.getElementById('githubUrl').value.trim();
        const issueNumber = document.getElementById('customIssueNumber').value.trim();
        
        const repoStatusEl = document.getElementById('repoValidationStatus');
        const issueStatusEl = document.getElementById('issueValidationStatus');
        const customRepoInfo = document.getElementById('customRepoInfo');
        
        if (!githubUrl) {
            repoStatusEl.innerHTML = '';
            return;
        }
        
        // 显示加载状态
        repoStatusEl.innerHTML = '<span class="text-muted"><i class="fas fa-spinner fa-spin me-1"></i>验证中...</span>';
        
        try {
            const response = await fetch('/api/validate_github_repo', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    github_url: githubUrl,
                    issue_number: issueNumber
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                // 仓库验证成功
                this.validatedRepoInfo = result;
                repoStatusEl.innerHTML = `
                    <div class="alert alert-success py-2 mb-0">
                        <i class="fas fa-check-circle me-1"></i>
                        仓库验证成功: ${result.repo_name}
                    </div>
                `;
                
                // 显示仓库信息
                if (result.repo_info) {
                    const repoDetails = document.getElementById('customRepoDetails');
                    repoDetails.innerHTML = `
                        <p class="mb-1"><strong>仓库:</strong> ${result.repo_name}</p>
                        <p class="mb-1"><strong>描述:</strong> ${result.repo_info.description || '无'}</p>
                        <p class="mb-1"><strong>语言:</strong> ${result.repo_info.language || '未知'}</p>
                        <p class="mb-0"><strong>Stars:</strong> ${result.repo_info.stars || 0} ⭐</p>
                    `;
                    customRepoInfo.classList.remove('d-none');
                }
                
                // 验证 Issue
                if (issueNumber && result.issue_valid) {
                    issueStatusEl.innerHTML = `
                        <div class="alert alert-success py-2 mb-0">
                            <i class="fas fa-check-circle me-1"></i>
                            Issue #${issueNumber} 验证成功: ${result.issue_info.title}
                        </div>
                    `;
                } else if (issueNumber && result.issue_valid === false) {
                    issueStatusEl.innerHTML = `
                        <div class="alert alert-warning py-2 mb-0">
                            <i class="fas fa-exclamation-triangle me-1"></i>
                            ${result.issue_error || 'Issue 不存在'}
                        </div>
                    `;
                } else {
                    issueStatusEl.innerHTML = '';
                }
                
            } else {
                // 仓库验证失败
                this.validatedRepoInfo = null;
                repoStatusEl.innerHTML = `
                    <div class="alert alert-danger py-2 mb-0">
                        <i class="fas fa-times-circle me-1"></i>
                        ${result.error}
                        ${result.hint ? '<br><small>' + result.hint + '</small>' : ''}
                    </div>
                `;
                customRepoInfo.classList.add('d-none');
            }
            
        } catch (error) {
            console.error('Error validating repository:', error);
            repoStatusEl.innerHTML = `
                <div class="alert alert-danger py-2 mb-0">
                    <i class="fas fa-times-circle me-1"></i>
                    验证失败，请检查网络连接
                </div>
            `;
        }
    }

    /**
     * 启动修复任务
     */
    async startRepairTask() {
        // 禁用提交按钮
        const submitBtn = document.getElementById('startRepairBtn');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="loading-spinner me-2"></span>启动中...';
        
        console.log('启动修复任务，当前模式:', this.isCustomMode ? '自定义' : '预定义');
        
        try {
            let requestData;
            
            if (this.isCustomMode) {
                // 自定义仓库模式
                const githubUrl = document.getElementById('githubUrl').value.trim();
                const issueNumber = document.getElementById('customIssueNumber').value.trim();
                
                console.log('自定义模式 - URL:', githubUrl, 'Issue:', issueNumber);
                
                if (!githubUrl || !issueNumber) {
                    this.showNotification('请填写 GitHub 仓库 URL 和 Issue 编号', 'error');
                    this.resetSubmitButton();
                    return;
                }
                
                // 验证 issueNumber 是否为数字
                if (!/^\d+$/.test(issueNumber)) {
                    this.showNotification('Issue 编号必须是数字', 'error');
                    this.resetSubmitButton();
                    return;
                }
                
                // 如果还没验证，先自动验证
                if (!this.validatedRepoInfo) {
                    this.showNotification('正在验证仓库...', 'info');
                    await this.validateGitHubRepo();
                    
                    // 验证后再检查
                    if (!this.validatedRepoInfo) {
                        this.showNotification('仓库验证失败，请检查 URL 是否正确', 'error');
                        this.resetSubmitButton();
                        return;
                    }
                }
                
                requestData = {
                    is_custom: true,
                    github_url: githubUrl,
                    issue_number: issueNumber
                };
                
            } else {
                // 预定义仓库模式
                const repoKey = document.getElementById('repoSelect').value;
                const issueNumber = document.getElementById('issueNumber').value.trim();
                
                console.log('预定义模式 - Repo:', repoKey, 'Issue:', issueNumber);
                
                if (!repoKey || !issueNumber) {
                    this.showNotification('请选择仓库并填写 Issue 编号', 'error');
                    this.resetSubmitButton();
                    return;
                }
                
                // 验证 issueNumber 是否为数字
                if (!/^\d+$/.test(issueNumber)) {
                    this.showNotification('Issue 编号必须是数字', 'error');
                    this.resetSubmitButton();
                    return;
                }
                
                requestData = {
                    is_custom: false,
                    repo_key: repoKey,
                    issue_number: issueNumber
                };
            }
            
            const response = await fetch('/api/start_repair', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestData)
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.currentTaskId = result.task_id;
                this.currentTask = {
                    instance_id: result.instance_id,
                    repo_name: result.repo_name,
                    is_custom: this.isCustomMode
                };
                
                if (this.isCustomMode) {
                    this.currentTask.issue_title = result.issue_title;
                } else {
                    this.currentTask.repo_key = requestData.repo_key;
                }
                
                this.showTaskInterface();
                this.showNotification(result.message, 'success');
                
                // 开始轮询任务状态
                this.startStatusPolling();
                
            } else {
                this.showNotification(result.error, 'error');
                this.resetSubmitButton();
            }
            
        } catch (error) {
            console.error('Error starting repair task:', error);
            this.showNotification('启动任务时发生错误', 'error');
            this.resetSubmitButton();
        }
    }

    /**
     * 重置提交按钮
     */
    resetSubmitButton() {
        const submitBtn = document.getElementById('startRepairBtn');
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-magic me-2"></i>开始修复';
    }

    /**
     * 显示任务界面
     */
    showTaskInterface() {
        document.getElementById('defaultStatus').classList.add('d-none');
        document.getElementById('taskStatus').classList.remove('d-none');
        
        // 填充任务信息
        document.getElementById('taskRepo').textContent = this.currentTask.repo_name;
        document.getElementById('taskInstance').textContent = this.currentTask.instance_id;
        
        // 重置进度
        this.updateProgress(0, '初始化...');
        
        // 清空日志
        document.getElementById('logContent').innerHTML = '';
        this.logBuffer = [];
    }

    /**
     * 开始状态轮询
     */
    startStatusPolling() {
        if (this.statusPollingInterval) {
            clearInterval(this.statusPollingInterval);
        }
        
        // 立即检查一次状态
        this.checkTaskStatus();
        
        // 每 2 秒检查一次状态
        this.statusPollingInterval = setInterval(() => {
            this.checkTaskStatus();
        }, 2000);
    }

    /**
     * 停止状态检查
     */
    stopStatusCheck() {
        if (this.statusPollingInterval) {
            clearInterval(this.statusPollingInterval);
            this.statusPollingInterval = null;
        }
    }

    /**
     * 检查任务状态
     */
    async checkTaskStatus() {
        if (!this.currentTaskId) return;
        
        try {
            const response = await fetch(`/api/task_status/${this.currentTaskId}`);
            
            // 如果任务不存在（404），停止查询
            if (response.status === 404) {
                console.log(`Task ${this.currentTaskId} not found, stopping status checks`);
                this.currentTaskId = null;
                this.stopStatusCheck();
                return;
            }
            
            const result = await response.json();
            
            if (result.success) {
                const task = result.task;
                const logs = result.logs;
                
                // 更新进度
                this.updateProgress(task.progress, task.current_step);
                
                // 更新日志（只添加新的日志）
                this.updateLogs(logs);
                
                // 检查任务是否完成
                if (task.status === 'completed') {
                    this.handleTaskCompletion(task);
                } else if (task.status === 'error') {
                    this.handleTaskError(task);
                }
                
            } else {
                console.error('Failed to get task status:', result.error);
            }
            
        } catch (error) {
            console.error('Error checking task status:', error);
        }
    }

    /**
     * 处理任务更新
     */
    handleTaskUpdate(data) {
        if (data.task_id !== this.currentTaskId) return;
        
        this.updateProgress(data.progress, data.message);
        
        // 更新进度条颜色
        const progressBar = document.getElementById('progressBar');
        if (data.status === 'completed') {
            progressBar.className = 'progress-bar bg-success';
        } else if (data.status === 'error') {
            progressBar.className = 'progress-bar bg-danger';
        }
    }

    /**
     * 处理任务日志
     */
    handleTaskLog(data) {
        if (data.task_id !== this.currentTaskId) return;
        
        this.addLogMessage(data.message);
    }

    /**
     * 处理任务进度
     */
    handleTaskProgress(data) {
        if (data.task_id !== this.currentTaskId) return;
        
        this.updateProgress(data.progress, data.step_detail);
    }

    /**
     * 更新进度
     */
    updateProgress(progress, message) {
        const progressBar = document.getElementById('progressBar');
        const progressPercent = document.getElementById('progressPercent');
        const currentStep = document.getElementById('currentStep');
        
        progressBar.style.width = `${progress}%`;
        progressPercent.textContent = `${progress}%`;
        currentStep.textContent = message;
    }

    /**
     * 更新日志
     */
    updateLogs(logs) {
        const logContent = document.getElementById('logContent');
        
        // 检查是否有新日志
        logs.forEach(log => {
            if (!this.logBuffer.includes(log)) {
                this.logBuffer.push(log);
                this.addLogMessage(log);
            }
        });
    }

    /**
     * 添加日志消息
     */
    addLogMessage(message) {
        const logContent = document.getElementById('logContent');
        const logContainer = document.getElementById('logContainer');
        
        const logLine = document.createElement('div');
        logLine.textContent = message;
        logLine.className = 'fade-in';
        
        logContent.appendChild(logLine);
        
        // 自动滚动到底部
        logContainer.scrollTop = logContainer.scrollHeight;
    }

    /**
     * 处理任务完成
     */
    handleTaskCompletion(task) {
        // 停止状态轮询
        if (this.statusPollingInterval) {
            clearInterval(this.statusPollingInterval);
        }
        
        // 显示完成操作
        document.getElementById('completedActions').classList.remove('d-none');
        
        // 重置提交按钮
        this.resetSubmitButton();
        
        this.showNotification('🎉 修复任务完成！', 'success');
    }

    /**
     * 处理任务错误
     */
    handleTaskError(task) {
        // 停止状态轮询
        if (this.statusPollingInterval) {
            clearInterval(this.statusPollingInterval);
        }
        
        // 重置提交按钮
        this.resetSubmitButton();
        
        const errorMsg = task.error || '修复任务执行失败';
        this.showNotification(`❌ ${errorMsg}`, 'error');
    }

    /**
     * 下载补丁
     */
    downloadPatch() {
        if (!this.currentTaskId || !this.currentTask) return;
        
        const downloadUrl = `/api/download_patch/${this.currentTaskId}`;
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = `${this.currentTask.instance_id}_patch.diff`;
        link.click();
        
        this.showNotification('开始下载补丁文件', 'info');
    }

    /**
     * 查看报告
     */
    viewReport() {
        if (!this.currentTask || !this.currentTaskId) return;
        
        // 打开补丁预览页面
        const patchViewUrl = `/patch_view/${this.currentTaskId}`;
        window.open(patchViewUrl, '_blank');
    }

    /**
     * 重置界面
     */
    resetInterface() {
        // 停止状态轮询
        if (this.statusPollingInterval) {
            clearInterval(this.statusPollingInterval);
        }
        
        // 重置状态
        this.currentTaskId = null;
        this.currentTask = null;
        this.logBuffer = [];
        this.validatedRepoInfo = null;
        
        // 重置界面
        document.getElementById('taskStatus').classList.add('d-none');
        document.getElementById('defaultStatus').classList.remove('d-none');
        document.getElementById('completedActions').classList.add('d-none');
        
        // 清空表单
        document.getElementById('repairForm').reset();
        document.getElementById('repoDescription').textContent = '';
        
        // 重置自定义仓库状态
        const repoStatusEl = document.getElementById('repoValidationStatus');
        const issueStatusEl = document.getElementById('issueValidationStatus');
        const customRepoInfo = document.getElementById('customRepoInfo');
        if (repoStatusEl) repoStatusEl.innerHTML = '';
        if (issueStatusEl) issueStatusEl.innerHTML = '';
        if (customRepoInfo) customRepoInfo.classList.add('d-none');
        
        // 重置提交按钮
        this.resetSubmitButton();
        
        // 重置示例按钮
        this.setupExampleButtons();
    }

    /**
     * 显示通知
     */
    showNotification(message, type = 'info') {
        // 创建通知元素
        const notification = document.createElement('div');
        notification.className = `alert alert-${this.getBootstrapAlertClass(type)} alert-dismissible fade show position-fixed`;
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        
        notification.innerHTML = `
            ${this.getNotificationIcon(type)} ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(notification);
        
        // 自动移除
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 5000);
    }

    /**
     * 获取 Bootstrap 警告类
     */
    getBootstrapAlertClass(type) {
        const classMap = {
            'success': 'success',
            'error': 'danger',
            'warning': 'warning',
            'info': 'info'
        };
        return classMap[type] || 'info';
    }

    /**
     * 获取通知图标
     */
    getNotificationIcon(type) {
        const iconMap = {
            'success': '<i class="fas fa-check-circle me-2"></i>',
            'error': '<i class="fas fa-exclamation-circle me-2"></i>',
            'warning': '<i class="fas fa-exclamation-triangle me-2"></i>',
            'info': '<i class="fas fa-info-circle me-2"></i>'
        };
        return iconMap[type] || iconMap['info'];
    }
}

// 页面加载完成后初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.kgCompassApp = new KGCompassApp();
});

// 添加一些实用工具函数
window.KGCompassUtils = {
    /**
     * 格式化时间戳
     */
    formatTimestamp(timestamp) {
        return new Date(timestamp).toLocaleString('zh-CN');
    },
    
    /**
     * 格式化文件大小
     */
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },
    
    /**
     * 复制文本到剪贴板
     */
    async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (err) {
            console.error('Failed to copy text: ', err);
            return false;
        }
    }
}; 