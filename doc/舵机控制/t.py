import serial
import time
import threading
from queue import Queue
import struct

class ServoController:
    def __init__(self, port='COM32', baudrate=115200):
        """
        初始化舵机控制器
        
        参数:
        - port: 串口号 (如 'COM32' 或 '/dev/ttyUSB0')
        - baudrate: 波特率
        """
        try:
            self.ser = serial.Serial(port, baudrate, timeout=0.1)
            print(f"成功连接到串口 {port}")
        except Exception as e:
            print(f"无法连接到串口 {port}: {e}")
            self.ser = None
        
        # 舵机ID映射 (你提供的ID范围)
        self.servo_ids = list(range(0x07, 0x11)) + list(range(0x00, 0x07))
        self.total_servos = len(self.servo_ids)  # 17个舵机
        
        # 舵机状态存储
        self.servo_status = {id: {
            'position': None,      # 当前位置
            'temperature': None,   # 温度
            'voltage': None,       # 电压
            'load': None,          # 负载
            'last_update': None,   # 最后更新时间
            'online': False        # 是否在线
        } for id in self.servo_ids}
        
        # 响应队列和线程
        self.response_queue = Queue()
        self.read_thread = None
        self.running = False
        
    def start(self):
        """启动读取线程"""
        if self.ser and not self.running:
            self.running = True
            self.read_thread = threading.Thread(target=self._read_responses)
            self.read_thread.daemon = True
            self.read_thread.start()
            print("响应读取线程已启动")
    
    def stop(self):
        """停止读取线程"""
        self.running = False
        if self.read_thread:
            self.read_thread.join(timeout=1)
            print("响应读取线程已停止")
    
    def _calculate_checksum(self, data):
        """计算校验和"""
        return (~sum(data)) & 0xFF
    
    def create_query_command(self, servo_id):
        """
        创建查询指令
        
        指令格式: FF FF [ID] 02 07 [CHECKSUM]
        """
        # 数据部分: ID + 指令长度 + 指令
        data = [servo_id, 0x02, 0x07]
        checksum = self._calculate_checksum(data)
        
        # 完整指令
        command = bytes([0xFF, 0xFF] + data + [checksum])
        return command
    
    def query_all_servos(self, interval=0.01):
        """
        查询所有舵机
        
        参数:
        - interval: 查询间隔(秒)
        """
        if not self.ser:
            print("错误：串口未连接")
            return False
        
        print(f"开始查询 {self.total_servos} 个舵机...")
        
        for servo_id in self.servo_ids:
            command = self.create_query_command(servo_id)
            try:
                self.ser.write(command)
                # print(f"查询舵机 0x{servo_id:02X}")
                time.sleep(interval)
            except Exception as e:
                print(f"查询舵机 0x{servo_id:02X} 失败: {e}")
        
        print("所有舵机查询指令已发送")
        return True
    
    def query_specific_servo(self, servo_id):
        """
        查询特定舵机
        
        参数:
        - servo_id: 舵机ID (十进制或十六进制)
        """
        if isinstance(servo_id, str) and servo_id.startswith('0x'):
            servo_id = int(servo_id, 16)
        
        if servo_id not in self.servo_ids:
            print(f"错误：舵机ID 0x{servo_id:02X} 无效")
            return False
        
        if not self.ser:
            print("错误：串口未连接")
            return False
        
        command = self.create_query_command(servo_id)
        try:
            self.ser.write(command)
            print(f"已发送查询指令到舵机 0x{servo_id:02X}")
            return True
        except Exception as e:
            print(f"查询失败: {e}")
            return False
    
    def _read_responses(self):
        """读取串口响应"""
        buffer = bytearray()
        
        while self.running:
            try:
                if self.ser.in_waiting > 0:
                    data = self.ser.read(self.ser.in_waiting)
                    buffer.extend(data)
                    
                    # 处理缓冲区中的数据
                    while len(buffer) >= 6:  # 最小响应长度
                        # 查找帧头 0xFF 0xFF
                        if buffer[0] != 0xFF or buffer[1] != 0xFF:
                            # 帧头不匹配，删除第一个字节
                            buffer.pop(0)
                            continue
                        
                        # 获取舵机ID和包长度
                        servo_id = buffer[2]
                        length = buffer[3]
                        
                        # 检查是否有足够的数据
                        if len(buffer) < length + 4:  # 2字节帧头 + 长度字节 + 数据 + 校验和
                            break
                        
                        # 提取完整数据包
                        packet = buffer[:length + 4]
                        
                        # 验证校验和
                        data_part = packet[2:-1]  # 从ID到校验和前
                        checksum = packet[-1]
                        
                        if self._calculate_checksum(data_part) == checksum:
                            # 校验和正确，处理数据包
                            self._process_response_packet(packet)
                        
                        # 从缓冲区中移除已处理的数据
                        buffer = buffer[length + 4:]
                        
            except Exception as e:
                print(f"读取响应错误: {e}")
                time.sleep(0.1)
    
    def _process_response_packet(self, packet):
        """处理响应数据包"""
        servo_id = packet[2]
        error = packet[4]
        
        if error != 0:
            print(f"舵机 0x{servo_id:02X} 返回错误: 0x{error:02X}")
            return
        
        # 解析位置信息（如果有）
        if len(packet) >= 8:
            # 位置数据通常在字节5和6
            position = (packet[5] << 8) | packet[6]
            
            # 更新舵机状态
            if servo_id in self.servo_status:
                self.servo_status[servo_id]['position'] = position
                self.servo_status[servo_id]['last_update'] = time.time()
                self.servo_status[servo_id]['online'] = True
                
                # 输出舵机信息
                self._print_servo_info(servo_id, position)
                
                # 发送到队列
                self.response_queue.put((servo_id, position))
    
    def _print_servo_info(self, servo_id, position):
        """打印舵机信息"""
        angle = int((position / 1023.0) * 300)  # 假设舵机范围0-300度
        print(f"舵机 0x{servo_id:02X} (ID:{servo_id:3d}) - 位置: {position:4d}, 角度: {angle:3d}°, 时间: {time.strftime('%H:%M:%S')}")
    
    def get_servo_status(self, servo_id=None):
        """
        获取舵机状态
        
        参数:
        - servo_id: 特定舵机ID，None表示获取所有
        """
        if servo_id is not None:
            if servo_id in self.servo_status:
                return self.servo_status[servo_id]
            return None
        else:
            return self.servo_status
    
    def wait_for_response(self, timeout=2.0):
        """
        等待响应
        
        参数:
        - timeout: 超时时间(秒)
        
        返回:
        - list: 收到的响应列表
        """
        responses = []
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = self.response_queue.get(timeout=0.1)
                responses.append(response)
            except:
                pass
            
            # 如果收到了所有舵机的响应，提前退出
            if len(responses) >= self.total_servos:
                break
        
        return responses
    
    def continuous_monitoring(self, interval=0.5):
        """连续监控模式"""
        print(f"进入连续监控模式，每 {interval} 秒查询一次")
        print("按 Ctrl+C 退出监控\n")
        
        try:
            while True:
                # 清空队列
                while not self.response_queue.empty():
                    self.response_queue.get()
                
                # 查询所有舵机
                self.query_all_servos()
                
                # 等待响应
                time.sleep(0.5)
                
                # 显示当前状态
                self.display_status()
                
                # 间隔
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n退出监控模式")
    
    def display_status(self, show_all=False):
        """显示舵机状态"""
        print("\n" + "="*60)
        print("舵机状态表")
        print("="*60)
        print("ID(HEX)  ID(DEC)  位置    角度    状态      最后更新")
        print("-"*60)
        
        online_count = 0
        for servo_id in self.servo_ids:
            status = self.servo_status[servo_id]
            
            if not show_all and not status['online']:
                continue
                
            if status['position'] is not None:
                position = status['position']
                angle = int((position / 1023.0) * 300)
                angle_str = f"{angle:3d}°"
                pos_str = f"{position:4d}"
            else:
                angle_str = " N/A"
                pos_str = " N/A"
            
            if status['online']:
                state = "在线"
                online_count += 1
            else:
                state = "离线"
            
            if status['last_update']:
                time_str = time.strftime('%H:%M:%S', time.localtime(status['last_update']))
            else:
                time_str = "从未"
            
            print(f"0x{servo_id:02X}     {servo_id:3d}     {pos_str}   {angle_str}   {state:4s}     {time_str}")
        
        print("-"*60)
        print(f"在线: {online_count}/{self.total_servos}  离线: {self.total_servos - online_count}")
        print("="*60)
    
    def create_position_command(self, servo_id, position):
        """
        创建位置控制指令
        
        参数:
        - servo_id: 舵机ID
        - position: 位置值 (0-1023)
        """
        # 确保位置在范围内
        if position < 0:
            position = 0
        elif position > 1023:
            position = 1023
        
        position = int(position)
        
        # 构造数据: ID + 长度 + 指令 + 位置(2字节)
        data = [
            servo_id,           # 舵机ID
            0x05,              # 长度
            0x03,              # 写入指令
            0x2A,              # 位置寄存器地址
            position & 0xFF,   # 位置低字节
            (position >> 8) & 0xFF  # 位置高字节
        ]
        
        checksum = self._calculate_checksum(data)
        
        # 完整指令
        command = bytes([0xFF, 0xFF] + data + [checksum])
        return command
    
    def move_servo(self, servo_id, position, delay=0.5):
        """
        移动舵机到指定位置
        
        参数:
        - servo_id: 舵机ID
        - position: 位置值 (0-1023)
        - delay: 移动后等待时间
        """
        if isinstance(servo_id, str) and servo_id.startswith('0x'):
            servo_id = int(servo_id, 16)
        
        if servo_id not in self.servo_ids:
            print(f"错误：舵机ID 0x{servo_id:02X} 无效")
            return False
        
        if not self.ser:
            print("错误：串口未连接")
            return False
        
        command = self.create_position_command(servo_id, position)
        angle = int((position / 1023.0) * 300)
        
        try:
            print(f"移动舵机 0x{servo_id:02X} 到位置 {position} ({angle}°)")
            self.ser.write(command)
            
            # 等待移动完成
            time.sleep(delay)
            
            # 查询新位置
            self.query_specific_servo(servo_id)
            
            return True
        except Exception as e:
            print(f"移动失败: {e}")
            return False
    
    def close(self):
        """关闭连接"""
        self.stop()
        if self.ser:
            self.ser.close()
            print("串口连接已关闭")


def interactive_control():
    """交互式控制界面"""
    print("="*60)
    print("舵机查询与控制系统")
    print("="*60)
    print(f"支持 {17} 个舵机 (ID: 0x00-0x06, 0x07-0x10)")
    print("\n可用命令:")
    print("  query [id/all] - 查询舵机状态 (id可为十进制或十六进制)")
    print("  move id position - 移动舵机到指定位置 (0-1023)")
    print("  angle id degrees - 移动舵机到指定角度 (0-300°)")
    print("  monitor - 进入连续监控模式")
    print("  status - 显示所有舵机状态")
    print("  test - 测试所有舵机")
    print("  help - 显示帮助")
    print("  exit - 退出程序")
    print("="*60)
    
    # 获取串口设置
    port = input("请输入串口号 (默认 COM32): ").strip() or 'COM32'
    baudrate = input("请输入波特率 (默认 115200): ").strip()
    baudrate = int(baudrate) if baudrate else 115200
    
    # 创建控制器
    try:
        controller = ServoController(port=port, baudrate=baudrate)
        if controller.ser is None:
            print("无法初始化控制器，请检查串口连接")
            return
        
        controller.start()
        print("系统就绪，输入命令开始控制...")
        
        while True:
            try:
                # 获取用户输入
                cmd_input = input("\n>>> ").strip().lower()
                
                if not cmd_input:
                    continue
                
                parts = cmd_input.split()
                command = parts[0]
                
                # 处理命令
                if command == 'exit' or command == 'quit':
                    print("退出程序")
                    break
                
                elif command == 'help':
                    print("\n命令详解:")
                    print("  query all           - 查询所有舵机")
                    print("  query 0x07          - 查询ID为0x07的舵机")
                    print("  query 7             - 查询ID为7的舵机")
                    print("  move 0x07 512       - 移动舵机到位置512")
                    print("  angle 0x07 150      - 移动舵机到150度")
                    print("  monitor             - 连续监控模式")
                    print("  status              - 显示状态")
                    print("  test                - 测试所有舵机响应")
                
                elif command == 'query':
                    if len(parts) < 2:
                        print("用法: query [id/all]")
                        continue
                    
                    target = parts[1]
                    
                    if target == 'all':
                        print("查询所有舵机...")
                        controller.query_all_servos()
                        
                        # 等待响应
                        responses = controller.wait_for_response(timeout=1.0)
                        
                        if responses:
                            print(f"收到 {len(responses)} 个舵机的响应:")
                            for servo_id, position in responses:
                                angle = int((position / 1023.0) * 300)
                                print(f"  舵机 0x{servo_id:02X}: 位置={position}, 角度={angle}°")
                        else:
                            print("未收到任何响应，请检查连接")
                    
                    else:
                        # 解析舵机ID
                        try:
                            if target.startswith('0x'):
                                servo_id = int(target, 16)
                            else:
                                servo_id = int(target)
                            
                            controller.query_specific_servo(servo_id)
                            
                            # 等待响应
                            responses = controller.wait_for_response(timeout=0.5)
                            
                            if responses:
                                for resp_servo_id, position in responses:
                                    if resp_servo_id == servo_id:
                                        angle = int((position / 1023.0) * 300)
                                        print(f"舵机 0x{servo_id:02X}: 位置={position}, 角度={angle}°")
                            else:
                                print(f"未收到舵机 0x{servo_id:02X} 的响应")
                        except ValueError:
                            print("错误：无效的舵机ID")
                
                elif command == 'move':
                    if len(parts) < 3:
                        print("用法: move id position")
                        print("示例: move 0x07 512")
                        continue
                    
                    try:
                        servo_id = int(parts[1], 0)  # 自动识别十进制或十六进制
                        position = int(parts[2])
                        
                        controller.move_servo(servo_id, position)
                    except ValueError:
                        print("错误：无效的参数")
                
                elif command == 'angle':
                    if len(parts) < 3:
                        print("用法: angle id degrees")
                        print("示例: angle 0x07 150")
                        continue
                    
                    try:
                        servo_id = int(parts[1], 0)
                        degrees = float(parts[2])
                        
                        # 将角度转换为位置 (0-1023)
                        position = int((degrees / 300.0) * 1023)
                        
                        if position < 0:
                            position = 0
                        elif position > 1023:
                            position = 1023
                        
                        controller.move_servo(servo_id, position)
                    except ValueError:
                        print("错误：无效的参数")
                
                elif command == 'monitor':
                    controller.continuous_monitoring()
                
                elif command == 'status':
                    controller.display_status(show_all=True)
                
                elif command == 'test':
                    print("开始舵机响应测试...")
                    controller.query_all_servos()
                    
                    # 等待响应
                    responses = controller.wait_for_response(timeout=2.0)
                    
                    if responses:
                        print(f"\n测试完成，收到 {len(responses)}/{controller.total_servos} 个舵机响应:")
                        for servo_id, position in responses:
                            angle = int((position / 1023.0) * 300)
                            print(f"  舵机 0x{servo_id:02X}: 位置={position}, 角度={angle}°")
                    else:
                        print("测试失败：未收到任何响应")
                
                else:
                    print(f"未知命令: {command}")
                    print("输入 'help' 查看可用命令")
            
            except KeyboardInterrupt:
                print("\n\n接收到中断信号")
                break
            except Exception as e:
                print(f"执行错误: {e}")
    
    except Exception as e:
        print(f"初始化失败: {e}")
    finally:
        if 'controller' in locals():
            controller.close()


def test_specific_commands():
    """测试特定的查询指令"""
    print("测试你提供的查询指令...")
    
    # 你提供的查询指令列表
    commands_hex = [
        "FF FF 07 02 07 10",
        "FF FF 08 02 07 11",
        "FF FF 09 02 07 12",
        "FF FF 0A 02 07 13",
        "FF FF 0B 02 07 14",
        "FF FF 0C 02 07 15",
        "FF FF 0D 02 07 16",
        "FF FF 0E 02 07 17",
        "FF FF 0F 02 07 18",
        "FF FF 10 02 07 19",
        "FF FF 00 02 07 09",
        "FF FF 01 02 07 0A",
        "FF FF 02 02 07 0B",
        "FF FF 03 02 07 0C",
        "FF FF 04 02 07 0D",
        "FF FF 05 02 07 0E",
        "FF FF 06 02 07 0F"
    ]
    
    # 转换为字节
    commands = [bytes.fromhex(cmd) for cmd in commands_hex]
    
    # 连接到串口
    port = input("请输入串口号 (默认 COM32): ").strip() or 'COM32'
    
    try:
        ser = serial.Serial(port, 115200, timeout=0.5)
        print(f"已连接到 {port}")
        
        print("\n开始发送查询指令...")
        
        for i, cmd in enumerate(commands):
            servo_id = cmd[2]  # 第三个字节是舵机ID
            print(f"发送指令 {i+1:2d}: 舵机 0x{servo_id:02X}...", end=' ')
            
            try:
                ser.write(cmd)
                
                # 尝试读取响应
                response = ser.read(100)  # 读取最多100字节
                
                if response:
                    print(f"收到响应: {response.hex().upper()}")
                    
                    # 解析位置信息
                    if len(response) >= 8:
                        position = (response[5] << 8) | response[6]
                        angle = int((position / 1023.0) * 300)
                        print(f"  舵机 0x{servo_id:02X}: 位置={position}, 角度={angle}°")
                    else:
                        print("  响应长度不足")
                else:
                    print("无响应")
                
                time.sleep(0.05)  # 短暂延迟
                
            except Exception as e:
                print(f"错误: {e}")
        
        print("\n所有指令发送完成")
        ser.close()
        
    except Exception as e:
        print(f"连接失败: {e}")


# 主程序入口
if __name__ == "__main__":
    print("舵机查询与控制系统")
    print("="*60)
    print("1. 交互式控制 (推荐)")
    print("2. 测试原始查询指令")
    print("3. 直接查询所有舵机")
    print("="*60)
    
    mode = input("请选择模式 (1-3): ").strip()
    
    if mode == '1':
        interactive_control()
    elif mode == '2':
        test_specific_commands()
    elif mode == '3':
        quick_test()
    else:
        print("无效选择，运行交互式控制")
        interactive_control()


def quick_test():
    """快速测试所有舵机"""
    port = input("请输入串口号 (默认 COM32): ").strip() or 'COM32'
    
    controller = ServoController(port=port)
    if controller.ser is None:
        return
    
    controller.start()
    
    print("\n快速测试 - 查询所有舵机")
    print("="*40)
    
    controller.query_all_servos()
    
    # 等待响应
    time.sleep(1)
    
    # 显示结果
    controller.display_status(show_all=True)
    
    controller.close()


# 简单的命令行示例
if __name__ == "__main__" and False:  # 设为False以避免直接运行
    # 快速使用示例
    controller = ServoController('COM32')
    controller.start()
    
    # 查询所有舵机
    controller.query_all_servos()
    
    # 等待并显示结果
    time.sleep(1)
    controller.display_status()
    
    # 移动一个舵机
    controller.move_servo(0x07, 512)  # 移动到中间位置
    
    controller.close()