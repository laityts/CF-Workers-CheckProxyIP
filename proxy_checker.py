import os
import requests
import socket
import json
from typing import List, Dict
from datetime import datetime

class ProxyChecker:
    def __init__(self):
        self.tg_bot_token = os.getenv('TG_BOT_TOKEN')
        self.tg_chat_id = os.getenv('TG_CHAT_ID')
        self.github_event_name = os.getenv('GITHUB_EVENT_NAME', 'schedule')
        
        # 加载配置
        self.config = self.load_config()
        # 加载代理列表
        self.proxy_targets = self.load_proxy_list()
        
        self.results = []
        self.has_failure = False
    
    def load_config(self) -> Dict:
        """加载配置文件"""
        default_config = {
            "check_api": "https://check.proxyip.eytan.netlib.re",
            "send_notification": "failure-only",
            "timeout": 30,
            "max_retries": 2,
            "default_port": 443
        }
        
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                default_config.update(user_config)
        except FileNotFoundError:
            print("配置文件 config.json 不存在，使用默认配置")
        except json.JSONDecodeError as e:
            print(f"配置文件格式错误: {e}，使用默认配置")
        except Exception as e:
            print(f"加载配置文件时出错: {e}，使用默认配置")
        
        print(f"加载配置: {default_config}")
        return default_config
    
    def load_proxy_list(self) -> List[str]:
        """加载代理列表文件"""
        targets = []
        try:
            with open('proxy_list.txt', 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过空行和注释
                    if line and not line.startswith('#'):
                        targets.append(line)
        except FileNotFoundError:
            print("代理列表文件 proxy_list.txt 不存在")
        except Exception as e:
            print(f"加载代理列表时出错: {e}")
        
        print(f"加载代理列表: {targets}")
        return targets
    
    def normalize_target(self, target: str) -> tuple:
        """规范化目标，处理默认端口"""
        target = target.strip()
        if not target:
            return None, None
        
        # 检查是否包含端口
        if ':' in target:
            # 处理IPv6地址
            if target.startswith('['):
                # IPv6地址格式 [::1]:8080
                end_bracket = target.find(']')
                if end_bracket == -1:
                    print(f"无效的IPv6格式: {target}")
                    return None, None
                host = target[1:end_bracket]
                if end_bracket + 1 < len(target) and target[end_bracket + 1] == ':':
                    port_str = target[end_bracket + 2:]
                else:
                    port_str = str(self.config.get('default_port', 443))
            else:
                # IPv4或域名格式
                parts = target.split(':', 1)
                host = parts[0]
                port_str = parts[1] if len(parts) > 1 else str(self.config.get('default_port', 443))
        else:
            # 没有端口，使用默认端口
            host = target
            port_str = str(self.config.get('default_port', 443))
        
        try:
            port = int(port_str)
            return host, port
        except ValueError:
            print(f"无效的端口: {port_str}")
            return None, None
    
    def resolve_domain(self, domain: str) -> List[str]:
        """解析域名获取所有IP地址"""
        try:
            result = socket.getaddrinfo(domain, None)
            ips = list(set([item[4][0] for item in result]))
            print(f"域名 {domain} 解析结果: {ips}")
            return ips
        except Exception as e:
            print(f"解析域名 {domain} 失败: {e}")
            return []
    
    def is_valid_ip(self, ip: str) -> bool:
        """检查是否为有效的IP地址"""
        try:
            socket.inet_pton(socket.AF_INET, ip)
            return True
        except socket.error:
            try:
                socket.inet_pton(socket.AF_INET6, ip)
                return True
            except socket.error:
                return False
    
    def check_proxy(self, ip: str, port: int, original_target: str = None) -> Dict:
        """检查单个代理IP"""
        max_retries = self.config.get('max_retries', 2)
        timeout = self.config.get('timeout', 30)
        
        for attempt in range(max_retries):
            try:
                proxy_str = f"{ip}:{port}"
                api_url = f"{self.config['check_api']}/check?proxyip={proxy_str}"
                
                print(f"检查代理: {proxy_str} (尝试 {attempt + 1}/{max_retries})")
                response = requests.get(api_url, timeout=timeout)
                data = response.json()
                
                result = {
                    'target': original_target or proxy_str,
                    'ip': ip,
                    'port': port,
                    'success': data.get('success', False),
                    'response_time': data.get('responseTime', 0),
                    'colo': data.get('colo', ''),
                    'message': data.get('message', ''),
                    'timestamp': data.get('timestamp', '')
                }
                
                status = "成功" if result['success'] else "失败"
                print(f"代理 {proxy_str} 检查{status}, 响应时间: {result['response_time']}ms")
                
                if not result['success']:
                    self.has_failure = True
                
                return result
                
            except requests.exceptions.Timeout:
                print(f"检查代理 {ip}:{port} 超时 (尝试 {attempt + 1}/{max_retries})")
                if attempt == max_retries - 1:
                    self.has_failure = True
                    return {
                        'target': original_target or f"{ip}:{port}",
                        'ip': ip,
                        'port': port,
                        'success': False,
                        'response_time': 0,
                        'colo': '',
                        'message': '请求超时',
                        'timestamp': ''
                    }
            except Exception as e:
                print(f"检查代理 {ip}:{port} 时出错: {e} (尝试 {attempt + 1}/{max_retries})")
                if attempt == max_retries - 1:
                    self.has_failure = True
                    return {
                        'target': original_target or f"{ip}:{port}",
                        'ip': ip,
                        'port': port,
                        'success': False,
                        'response_time': 0,
                        'colo': '',
                        'message': f'检查失败: {str(e)}',
                        'timestamp': ''
                    }
    
    def process_target(self, target: str) -> List[Dict]:
        """处理单个目标（域名或IP）"""
        results = []
        
        host, port = self.normalize_target(target)
        if host is None or port is None:
            return results
        
        # 判断是域名还是IP
        if self.is_valid_ip(host):
            # 如果是有效的IP地址
            results.append(self.check_proxy(host, port, target))
        else:
            # 如果是域名，解析所有IP并检查
            print(f"解析域名: {host}")
            ips = self.resolve_domain(host)
            if not ips:
                print(f"域名 {host} 解析失败，尝试直接检查")
                results.append(self.check_proxy(host, port, target))
            else:
                for ip in ips:
                    results.append(self.check_proxy(ip, port, target))
        
        return results
    
    def format_message(self) -> str:
        """格式化通知消息"""
        # 获取当前时间
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if self.github_event_name == 'workflow_dispatch':
            message = f"🔄 手动检查 - 代理服务器状态\n"
        else:
            message = f"⏰ 定时检查 - 代理服务器状态\n"
        
        message += f"⏱️ 检查时间: {current_time}\n\n"
        
        # 按目标分组结果
        target_groups = {}
        for result in self.results:
            target = result['target']
            if target not in target_groups:
                target_groups[target] = []
            target_groups[target].append(result)
        
        # 显示每个目标的结果
        for target, results in target_groups.items():
            # 获取目标的显示名称（去掉端口部分）
            display_target = target.split(':')[0] if ':' in target else target
            
            # 判断目标是IP还是域名
            if self.is_valid_ip(display_target):
                # IP地址
                message += f"📍 IP: {display_target}\n"
            else:
                # 域名
                message += f"🌐 域名: {display_target}\n"
            
            # 显示每个IP的结果
            for result in results:
                if result['success']:
                    status = "✅ 正常"
                    details = f"{result['response_time']}ms"
                    message += f"- {result['ip']}:{result['port']} {status} - {details}\n"
                else:
                    status = "❌ 失败"
                    message += f"- {result['ip']}:{result['port']} {status} - {result['message']}\n"
            
            message += "\n"
        
        # 检查配置
        message += f"🔧 检查配置\n"
        message += f"   ├ 触发方式: {'手动触发' if self.github_event_name == 'workflow_dispatch' else '定时任务'}\n"
        # 从API URL中去掉路径部分，只显示域名
        api_base = self.config['check_api'].split('/check')[0] if '/check' in self.config['check_api'] else self.config['check_api']
        message += f"   ├ 检测API: {api_base}\n"
        message += f"   └ 默认端口: {self.config.get('default_port', 443)}"
        
        return message
    
    def send_telegram_notification(self, message: str):
        """发送Telegram通知"""
        if not self.tg_bot_token or not self.tg_chat_id:
            print("缺少Telegram配置，跳过通知发送")
            return
        
        url = f"https://api.telegram.org/bot{self.tg_bot_token}/sendMessage"
        payload = {
            'chat_id': self.tg_chat_id,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                print("✅ Telegram通知发送成功")
            else:
                print(f"❌ Telegram通知发送失败: {response.text}")
        except Exception as e:
            print(f"❌ 发送Telegram通知时出错: {e}")
    
    def should_send_notification(self) -> bool:
        """判断是否应该发送通知"""
        send_notification = self.config.get('send_notification', 'failure-only')
        
        if send_notification == 'never':
            return False
        elif send_notification == 'always':
            return True
        elif send_notification == 'failure-only':
            return self.has_failure
        else:
            return self.has_failure
    
    def run(self):
        """主执行函数"""
        print("=" * 50)
        print("开始代理服务器检查")
        print(f"检查目标数量: {len(self.proxy_targets)}")
        print(f"检测API: {self.config['check_api']}")
        print(f"通知设置: {self.config['send_notification']}")
        print(f"触发方式: {self.github_event_name}")
        print(f"默认端口: {self.config.get('default_port', 443)}")
        print("=" * 50)
        
        if not self.proxy_targets:
            print("❌ 代理列表为空，请在 proxy_list.txt 中添加代理服务器")
            return
        
        print(f"开始检查 {len(self.proxy_targets)} 个代理服务器...")
        
        # 处理所有目标
        for target in self.proxy_targets:
            results = self.process_target(target)
            self.results.extend(results)
        
        # 生成报告
        message = self.format_message()
        print("\n" + "=" * 50)
        print("检查完成!")
        print("=" * 50)
        print(message)
        
        # 决定是否发送通知
        if self.should_send_notification():
            print("发送Telegram通知...")
            self.send_telegram_notification(message)
        else:
            print("无需发送通知")
            
        # 如果有失败且设置了失败时退出，则返回非零退出码
        if self.has_failure:
            print("⚠️ 检测到失败的代理服务器")
            exit(1)
        else:
            print("✅ 所有代理服务器正常")
            exit(0)

if __name__ == "__main__":
    checker = ProxyChecker()
    checker.run()
