"""
GitHub API 中间件
处理 GitHub API 调用的速率限制、分页、重试和 1000 结果限制突破
"""

import time
from datetime import datetime, timedelta
from github import Github
from typing import List, Optional, Tuple


class GitHubAPIMiddleware:
    """
    GitHub API 中间件，处理：
    1. 速率限制自动等待
    2. 自动重试机制
    3. 突破 search_issues 的 1000 结果限制
    4. 简单的结果缓存
    """
    
    def __init__(self, github_token: str, rate_limit_padding: int = 5, max_retries: int = 3):
        """
        初始化 GitHub API 中间件
        
        Args:
            github_token: GitHub API token
            rate_limit_padding: 速率限制保护余量（保留几次请求不用）
            max_retries: 最大重试次数
        """
        self.github = Github(github_token)
        self.rate_limit_padding = rate_limit_padding
        self.max_retries = max_retries
        self.cache = {}
        
    def _check_rate_limit(self, api_type: str = 'search'):
        """
        检查并等待速率限制
        
        Args:
            api_type: API 类型，'search' 或 'core'
        """
        try:
            rate_limit = self.github.get_rate_limit()
            
            if api_type == 'search':
                limit_info = rate_limit.search
            else:
                limit_info = rate_limit.core
            
            if limit_info.remaining < self.rate_limit_padding:
                reset_time = limit_info.reset.timestamp()
                wait_time = max(0, reset_time - time.time()) + 1
                print(f"⚠️  接近速率限制 ({api_type})。等待 {wait_time:.0f} 秒...")
                time.sleep(wait_time)
            elif limit_info.remaining < 10:
                # 剩余次数较少时，给出警告
                print(f"⚠️  {api_type} API 剩余调用次数: {limit_info.remaining}/{limit_info.limit}")
        except Exception as e:
            print(f"⚠️  无法检查速率限制: {e}")
            
    def _execute_with_retry(self, func, *args, **kwargs):
        """
        带重试机制的执行函数
        
        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数
            
        Returns:
            函数执行结果
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                    print(f"⚠️  尝试 {attempt + 1}/{self.max_retries} 失败: {e}")
                    print(f"   {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"❌ 所有 {self.max_retries} 次尝试均失败")
                    raise last_exception
                    
    def search_issues(self, query: str, max_results: Optional[int] = None, use_cache: bool = True):
        """
        增强的 search_issues 方法，自动处理分页和 1000 结果限制
        
        Args:
            query: GitHub 搜索查询字符串
            max_results: 最大返回结果数（None 表示不限制）
            use_cache: 是否使用缓存
            
        Returns:
            List of issues
        """
        cache_key = f"search:{query}:{max_results}"
        
        # 检查缓存
        if use_cache and cache_key in self.cache:
            print(f"📦 从缓存获取: {query[:60]}...")
            return self.cache[cache_key]
        
        # 检查速率限制
        self._check_rate_limit('search')
        
        # 执行搜索
        print(f"🔍 搜索: {query[:60]}...")
        results = self._execute_with_retry(self.github.search_issues, query)
        total_count = results.totalCount
        
        print(f"   找到 {total_count} 个结果")
        
        # GitHub API 限制：totalCount 最多只会显示 1000
        # 所以当 totalCount == 1000 时，实际可能有更多结果，需要分段查询
        if total_count >= 1000:
            print(f"⚠️  结果超过 1000，使用时间分段查询...")
            all_issues = self._search_with_time_segmentation(query, max_results)
        else:
            # 获取所有结果（或限制数量）
            all_issues = []
            fetched = 0
            
            for issue in results:
                all_issues.append(issue)
                fetched += 1
                
                if max_results and fetched >= max_results:
                    break
                    
                # 每获取 100 个显示进度
                if fetched % 100 == 0:
                    print(f"   已获取 {fetched}/{min(total_count, max_results) if max_results else total_count} 个 issues...")
                    # 避免速率限制
                    time.sleep(0.5)
        
        print(f"✅ 共获取 {len(all_issues)} 个 issues")
        
        # 缓存结果
        if use_cache:
            self.cache[cache_key] = all_issues
            
        return all_issues
    
    def _search_with_time_segmentation(self, query: str, max_results: Optional[int] = None) -> List:
        """
        通过时间分段来处理超过 1000 结果的情况
        
        Args:
            query: 原始查询字符串
            max_results: 最大返回结果数
            
        Returns:
            List of issues
        """
        import re
        
        # 从查询中提取时间范围
        time_pattern = r'created:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})'
        time_match = re.search(time_pattern, query)
        
        if not time_match:
            # 如果没有时间范围，使用默认的宽范围并递归分割
            print("   查询中没有时间范围，将按年份分段查询...")
            return self._search_without_time_range(query, max_results)
        
        start_date_str = time_match.group(1)
        end_date_str = time_match.group(2)
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        
        # 计算时间跨度
        total_days = (end_date - start_date).days
        
        # 根据时间跨度决定分段策略，确保每段结果数不超过 900
        if total_days > 365:
            # 按季度（3个月，约90天）分段
            num_segments = (total_days // 90) + 1
            print(f"   时间跨度 {total_days} 天，分成 {num_segments} 段（每段约 90 天）")
        elif total_days > 180:
            # 按月分段
            num_segments = (total_days // 30) + 1
            print(f"   时间跨度 {total_days} 天，分成 {num_segments} 段（每段约 30 天）")
        else:
            # 按两周分段
            num_segments = max(2, (total_days // 14) + 1)
            print(f"   时间跨度 {total_days} 天，分成 {num_segments} 段（每段约 14 天）")
        
        all_issues = []
        segment_duration = total_days / num_segments
        
        for i in range(num_segments):
            segment_start = start_date + timedelta(days=i * segment_duration)
            segment_end = start_date + timedelta(days=(i + 1) * segment_duration)
            
            # 确保最后一段包含结束日期
            if i == num_segments - 1:
                segment_end = end_date
            
            segment_start_str = segment_start.strftime('%Y-%m-%d')
            segment_end_str = segment_end.strftime('%Y-%m-%d')
            
            # 构建新的查询
            segment_query = re.sub(
                time_pattern,
                f'created:{segment_start_str}..{segment_end_str}',
                query
            )
            
            print(f"   段 {i+1}/{num_segments}: {segment_start_str} 到 {segment_end_str}")
            
            # 检查速率限制
            self._check_rate_limit('search')
            
            segment_results = self._execute_with_retry(self.github.search_issues, segment_query)
            segment_count = segment_results.totalCount
            
            print(f"      该段有 {segment_count} 个结果")
            
            # 如果某个段达到或接近 1000，递归分割（使用 900 作为阈值更安全）
            if segment_count >= 900:
                print(f"      该段结果较多（{segment_count}），继续分割...")
                segment_issues = self._search_with_time_segmentation(
                    segment_query,
                    max_results - len(all_issues) if max_results else None
                )
            else:
                # 获取该段的所有结果
                segment_issues = list(segment_results)
            
            all_issues.extend(segment_issues)
            
            print(f"      当前已获取总计 {len(all_issues)} 个 issues")
            
            # 如果已达到最大结果数，退出
            if max_results and len(all_issues) >= max_results:
                return all_issues[:max_results]
            
            # 避免速率限制
            time.sleep(2)
        
        return all_issues
    
    def _search_without_time_range(self, query: str, max_results: Optional[int] = None) -> List:
        """
        对没有时间范围的查询进行分段处理
        
        Args:
            query: 原始查询字符串
            max_results: 最大返回结果数
            
        Returns:
            List of issues
        """
        # 从当前年份往前推，按年份分段查询
        current_year = datetime.now().year
        all_issues = []
        
        # 往前查 10 年（可以根据需要调整）
        for year in range(current_year, current_year - 10, -1):
            start_date = f"{year}-01-01"
            end_date = f"{year}-12-31"
            
            # 添加时间范围到查询
            timed_query = f"{query} created:{start_date}..{end_date}"
            
            print(f"   查询 {year} 年的 issues...")
            
            # 检查速率限制
            self._check_rate_limit('search')
            
            try:
                year_results = self._execute_with_retry(self.github.search_issues, timed_query)
                year_count = year_results.totalCount
                
                print(f"      {year} 年有 {year_count} 个结果")
                
                if year_count >= 900:
                    # 按月分割
                    print(f"      {year} 年结果较多（{year_count}），按月查询...")
                    year_issues = self._search_by_month(query, year)
                else:
                    year_issues = list(year_results)
                
                all_issues.extend(year_issues)
                
                # 如果已达到最大结果数，退出
                if max_results and len(all_issues) >= max_results:
                    return all_issues[:max_results]
                
                # 如果某年没有结果，可能已经查完所有 issues
                if year_count == 0:
                    break
                    
                # 避免速率限制
                time.sleep(2)
                
            except Exception as e:
                print(f"      查询 {year} 年时出错: {e}")
                continue
        
        return all_issues
    
    def _search_by_month(self, base_query: str, year: int) -> List:
        """
        按月份查询某一年的数据
        
        Args:
            base_query: 基础查询字符串（不含时间范围）
            year: 年份
            
        Returns:
            List of issues
        """
        all_issues = []
        
        for month in range(1, 13):
            # 计算该月的起止日期
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year, 12, 31)
            else:
                end_date = datetime(year, month + 1, 1) - timedelta(days=1)
            
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            
            month_query = f"{base_query} created:{start_str}..{end_str}"
            
            # 检查速率限制
            self._check_rate_limit('search')
            
            try:
                month_results = self._execute_with_retry(self.github.search_issues, month_query)
                month_count = month_results.totalCount
                
                if month_count > 0:
                    print(f"         {year}-{month:02d}: {month_count} 个结果")
                    
                if month_count >= 900:
                    print(f"         警告: {year}-{month:02d} 结果较多（{month_count}），可能无法获取全部")
                
                month_issues = list(month_results)
                all_issues.extend(month_issues)
                
                # 避免速率限制
                time.sleep(1)
                
            except Exception as e:
                print(f"         查询 {year}-{month:02d} 时出错: {e}")
                continue
        
        return all_issues
    
    def get_issue(self, repo_name: str, issue_number: int, use_cache: bool = True):
        """
        获取单个 issue
        
        Args:
            repo_name: 仓库名称（格式: owner/repo）
            issue_number: issue 编号
            use_cache: 是否使用缓存
            
        Returns:
            Issue object
        """
        cache_key = f"issue:{repo_name}:{issue_number}"
        
        # 检查缓存
        if use_cache and cache_key in self.cache:
            return self.cache[cache_key]
        
        # 检查速率限制
        self._check_rate_limit('core')
        
        # 获取 issue
        repo = self._execute_with_retry(self.github.get_repo, repo_name)
        issue = self._execute_with_retry(repo.get_issue, issue_number)
        
        # 缓存结果
        if use_cache:
            self.cache[cache_key] = issue
        
        return issue
    
    def get_rate_limit_status(self) -> dict:
        """
        获取当前速率限制状态
        
        Returns:
            速率限制信息字典
        """
        rate_limit = self.github.get_rate_limit()
        return {
            'core': {
                'remaining': rate_limit.core.remaining,
                'limit': rate_limit.core.limit,
                'reset': rate_limit.core.reset.strftime('%Y-%m-%d %H:%M:%S'),
                'used': rate_limit.core.limit - rate_limit.core.remaining
            },
            'search': {
                'remaining': rate_limit.search.remaining,
                'limit': rate_limit.search.limit,
                'reset': rate_limit.search.reset.strftime('%Y-%m-%d %H:%M:%S'),
                'used': rate_limit.search.limit - rate_limit.search.remaining
            }
        }
    
    def clear_cache(self):
        """清除缓存"""
        self.cache.clear()
        print("✅ 缓存已清除")

