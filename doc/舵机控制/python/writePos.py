import serial
import time

class MotorController23:
    def __init__(self, port='COM32', baudrate=115200):
        """初始化23电机控制器"""
        self.port = port
        self.baudrate = baudrate
        self.num_motors = 23  # 总共23个电机
        self.ser = None
        
        # 初始化指令（每次运行先发送）
        self.init_command = bytes.fromhex("FF FF FE 03 02 01 04")
        
        # 解析示例指令中的电机角度
        self.motor_angles = self.parse_example_angles()
        
        # 固定的前7个字节
        self.header_fixed = bytes.fromhex("FF FF FE 32 FE 01 BB")
    
    def parse_example_angles(self):
        """从示例指令中解析电机角度"""
        example_hex = "FF FF FE 32 FE 01 BB 01 10 01 64 01 CD 02 72 02 0F 02 D5 00 DA 01 BE 01 D6 01 CD 01 C1 02 EA 02 CF 00 B9 01 D3 01 D3 01 CD 01 CD 01 CD 01 82 00 00 00 00 01 CD 63"
        example_bytes = bytes.fromhex(example_hex.replace(" ", ""))
        
        angles = []
        # 从第8字节开始是电机角度（前7字节是固定的）
        # 电机ID从1开始，所以索引0对应电机1，索引22对应电机23
        for i in range(self.num_motors):
            start_idx = 7 + i * 2  # 第7字节后开始（0-based索引）
            low_byte = example_bytes[start_idx]
            high_byte = example_bytes[start_idx + 1]
            angle = (high_byte << 8) | low_byte
            angles.append(angle)
        
        return angles
    
    def connect(self):
        """连接串口"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1
            )
            print(f"串口 {self.port} 已连接，波特率 {self.baudrate}")
            return True
        except serial.SerialException as e:
            print(f"无法打开串口 {self.port}: {e}")
            return False
    
    def send_init_command(self):
        """发送初始化指令"""
        if not self.ser or not self.ser.is_open:
            print("错误：串口未连接")
            return False
        
        try:
            print(f"发送初始化指令: {self.init_command.hex().upper()}")
            self.ser.write(self.init_command)
            time.sleep(0.05)
            
            # 读取响应
            self.read_response()
            print("初始化指令发送完成")
            return True
        except Exception as e:
            print(f"发送初始化指令时出错: {e}")
            return False
    
    def disconnect(self):
        """断开串口连接"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("串口已关闭")
    
    def calculate_checksum(self, data_bytes):
        """计算校验和：从第3字节开始到最后一个字节求和，取低8位"""
        if len(data_bytes) < 3:
            return 0
        
        # 从第3字节开始到最后一个字节
        calc_range = data_bytes[2:]  # 索引2开始到结束
        checksum = sum(calc_range) & 0xFF
        return checksum
    
    def angle_to_bytes(self, angle):
        """将角度值(0-1023)转换为两个字节（小端序）"""
        if angle < 0:
            angle = 0
        elif angle > 1023:
            angle = 1023
        
        # 转换为两个字节（大端序）：低字节在前，高字节在后
        low_byte = (angle >> 8) & 0xFF
        high_byte = angle & 0xFF
        return low_byte, high_byte
    
    def create_motor_command(self, motor_angles):
        """创建电机控制指令"""
        # 指令格式：
        # 字节1-7: 固定头 FF FF FE 32 FE 01 BB
        # 字节8-53: 23个电机角度（46字节）
        # 字节54: 校验和
        
        if len(motor_angles) != self.num_motors:
            print(f"错误：需要{self.num_motors}个电机角度，但提供了{len(motor_angles)}个")
            return None
        
        # 开始构建指令
        data_list = []
        
        # 1. 添加固定头（7字节）
        data_list.extend(self.header_fixed)
        
        # 2. 添加电机角度数据（46字节）
        for angle in motor_angles:
            low_byte, high_byte = self.angle_to_bytes(angle)
            data_list.append(low_byte)
            data_list.append(high_byte)
        
        # 转换为字节数组
        data_bytes = bytes(data_list)
        
        # 计算校验和（从第3字节FE开始到最后一个数据字节）
        checksum = self.calculate_checksum(data_bytes)
        
        # 完整指令：数据 + 校验和
        full_command = data_bytes + bytes([checksum])
        
        return full_command
    
    def send_motor_command(self, motor_angles=None):
        """发送电机控制指令"""
        if not self.ser or not self.ser.is_open:
            print("错误：串口未连接")
            return False
        
        if motor_angles is None:
            motor_angles = self.motor_angles
        else:
            self.motor_angles = motor_angles.copy()
        
        try:
            # 创建指令
            command = self.create_motor_command(motor_angles)
            if command is None:
                return False
            
            # 显示指令
            hex_str = command.hex().upper()
            formatted = ' '.join([hex_str[i:i+2] for i in range(0, len(hex_str), 2)])
            
            print(f"发送指令（{len(command)}字节）:")
            print(formatted)
            
            # 验证长度
            expected_length = 54
            if len(command) == expected_length:
                print(f"✓ 指令长度正确：{len(command)}字节")
            else:
                print(f"✗ 指令长度错误：应为{expected_length}字节，实际为{len(command)}字节")
            
            # 解析指令内容
            print("\n指令解析:")
            print(f"固定头 (1-7字节): {' '.join([f'{b:02X}' for b in command[:7]])}")
            
            print("\n电机角度 (ID 1-23):")
            for i in range(self.num_motors):
                motor_id = i + 1  # 电机ID从1开始
                start_idx = 7 + i * 2  # 从第8字节开始
                low_byte = command[start_idx]
                high_byte = command[start_idx + 1]
                angle = (high_byte << 8) | low_byte
                print(f"  电机 {motor_id:2d}: {low_byte:02X} {high_byte:02X} = {angle:4d}")
            
            # 校验和
            calc_checksum = self.calculate_checksum(command[:-1])
            actual_checksum = command[-1]
            print(f"\n校验和: 计算={calc_checksum:02X}, 实际={actual_checksum:02X}, {'✓ 匹配' if calc_checksum == actual_checksum else '✗ 不匹配'}")
            
            print("-" * 60)
            
            # 发送指令
            self.ser.write(command)
            time.sleep(0.05)
            
            # 读取响应
            self.read_response()
            
            return True
            
        except Exception as e:
            print(f"发送指令时出错: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def set_motor_angle(self, motor_id, angle):
        """设置单个电机角度，电机ID从1开始"""
        if motor_id < 1 or motor_id > self.num_motors:
            print(f"错误：电机ID {motor_id} 超出范围 (1-{self.num_motors})")
            return False
        
        # 电机ID从1开始，但在数组中索引从0开始
        array_index = motor_id - 1
        self.motor_angles[array_index] = angle
        return self.send_motor_command()
    
    def set_multiple_motors(self, motor_dict):
        """设置多个电机角度，电机ID从1开始"""
        success = True
        for motor_id, angle in motor_dict.items():
            if motor_id < 1 or motor_id > self.num_motors:
                print(f"错误：电机ID {motor_id} 超出范围 (1-{self.num_motors})")
                success = False
            else:
                array_index = motor_id - 1
                self.motor_angles[array_index] = angle
        
        if success:
            return self.send_motor_command()
        return False
    
    def set_all_motors(self, angle):
        """设置所有电机到同一角度"""
        self.motor_angles = [angle] * self.num_motors
        return self.send_motor_command()
    
    def reset_to_example(self):
        """重置到示例指令的角度"""
        self.motor_angles = self.parse_example_angles()
        return self.send_motor_command()
    
    def read_response(self):
        """读取串口返回数据"""
        try:
            if self.ser.in_waiting > 0:
                response = self.ser.read(self.ser.in_waiting)
                if response:
                    hex_str = response.hex().upper()
                    formatted = ' '.join([hex_str[i:i+2] for i in range(0, len(hex_str), 2)])
                    print(f"收到响应 ({len(response)}字节): {formatted}")
                    
                    # 尝试解析响应中的ID
                    if len(response) >= 3:
                        if response[0] == 0xFF and response[1] == 0xFF:
                            motor_id = response[2]
                            print(f"来自电机 ID: {motor_id}")
        except:
            pass
    
    def analyze_example_instruction(self):
        """详细分析示例指令"""
        example_hex = "FF FF FE 32 FE 01 BB 01 10 01 64 01 CD 02 72 02 0F 02 D5 00 DA 01 BE 01 D6 01 CD 01 C1 02 EA 02 CF 00 B9 01 D3 01 D3 01 CD 01 CD 01 CD 01 82 00 00 00 00 01 CD 63"
        example_bytes = bytes.fromhex(example_hex.replace(" ", ""))
        
        print("\n" + "="*60)
        print("分析示例指令")
        print("="*60)
        
        print(f"总长度: {len(example_bytes)} 字节")
        
        # 解析固定头
        print(f"\n固定头 (1-7字节):")
        for i in range(7):
            print(f"  字节{i+1:2d}: {example_bytes[i]:02X}")
        
        # 解析电机角度
        print(f"\n电机角度 (8-53字节，共46字节，电机ID 1-23):")
        for i in range(self.num_motors):
            motor_id = i + 1  # 电机ID从1开始
            start_idx = 7 + i * 2
            low_byte = example_bytes[start_idx]
            high_byte = example_bytes[start_idx + 1]
            angle = (high_byte << 8) | low_byte
            print(f"  电机 {motor_id:2d}: 字节{start_idx+1:2d}-{start_idx+2:2d} = {low_byte:02X} {high_byte:02X} = {angle:4d}")
        
        # 校验和
        checksum = example_bytes[-1]
        print(f"\n校验和 (字节54): {checksum:02X}")
        
        # 验证校验和
        calc_checksum = self.calculate_checksum(example_bytes[:-1])
        print(f"计算校验和: {calc_checksum:02X}")
        print(f"校验和验证: {'✓ 通过' if calc_checksum == checksum else '✗ 失败'}")
        
        # 特别说明
        print(f"\n特别说明:")
        print(f"  电机21 (ID 21): 字节49-50 = {example_bytes[48]:02X} {example_bytes[49]:02X} = 0")
        print(f"  电机22 (ID 22): 字节51-52 = {example_bytes[50]:02X} {example_bytes[51]:02X} = {0x8201} = 33281")
    
    def verify_instruction_generation(self):
        """验证指令生成是否正确"""
        print("\n" + "="*60)
        print("验证指令生成")
        print("="*60)
        
        # 使用示例角度生成指令
        command = self.create_motor_command(self.motor_angles)
        if command is None:
            return False
        
        hex_str = command.hex().upper()
        formatted = ' '.join([hex_str[i:i+2] for i in range(0, len(hex_str), 2)])
        
        # 示例指令
        example_hex = "FF FF FE 32 FE 01 BB 01 10 01 64 01 CD 02 72 02 0F 02 D5 00 DA 01 BE 01 D6 01 CD 01 C1 02 EA 02 CF 00 B9 01 D3 01 D3 01 CD 01 CD 01 CD 01 82 00 00 00 00 01 CD 63"
        
        print("生成的指令:")
        print(formatted)
        print(f"\n长度: {len(command)}字节")
        
        if formatted == example_hex:
            print("\n✓ 生成的指令与示例指令完全一致！")
            return True
        else:
            print("\n✗ 生成的指令与示例指令不一致")
            
            # 详细比较
            gen_bytes = command
            exp_bytes = bytes.fromhex(example_hex.replace(" ", ""))
            
            min_len = min(len(gen_bytes), len(exp_bytes))
            for i in range(min_len):
                if gen_bytes[i] != exp_bytes[i]:
                    print(f"  字节{i+1:2d}: 生成={gen_bytes[i]:02X}, 示例={exp_bytes[i]:02X}")
            
            if len(gen_bytes) != len(exp_bytes):
                print(f"  长度不同: 生成={len(gen_bytes)}字节, 示例={len(exp_bytes)}字节")
            
            return False

def main():
    # 创建电机控制器
    controller = MotorController23(port='COM32', baudrate=115200)
    
    # 连接串口
    if not controller.connect():
        return
    
    try:
        # 发送初始化指令
        print("\n正在发送初始化指令...")
        if controller.send_init_command():
            print("初始化成功！")
        else:
            print("初始化失败，继续执行其他命令...")
        
        # 分析示例指令
        controller.analyze_example_instruction()
        
        # 验证指令生成
        controller.verify_instruction_generation()
        
        print("\n" + "="*60)
        print("23电机控制系统")
        print("="*60)
        print("\n注意：电机ID从1开始（1-23）")
        print("\n命令说明:")
        print("  set [id] [angle]      - 设置单个电机角度 (0-1023)")
        print("  multi id1 angle1 id2 angle2 ... - 设置多个电机")
        print("  all [angle]           - 设置所有电机到同一角度")
        print("  analyze               - 分析示例指令")
        print("  verify                - 验证指令生成")
        print("  status                - 显示当前所有电机角度")
        print("  reset                 - 重置到示例指令的角度")
        print("  test                  - 测试发送当前指令")
        print("  init                  - 重新发送初始化指令")
        print("  exit                  - 退出程序")
        print("\n示例:")
        print("  set 21 0              # 设置电机21到角度0")
        print("  set 1 300             # 设置电机1到角度300")
        print("  multi 1 300 2 600 3 900  # 同时设置多个电机")
        print("  all 512               # 所有电机复位到512")
        print("="*60)
        
        while True:
            user_input = input("\n请输入命令: ").strip()
            
            if not user_input:
                continue
                
            cmd = user_input.lower()
            
            if cmd == 'exit':
                break
            elif cmd == 'analyze':
                controller.analyze_example_instruction()
            elif cmd == 'verify':
                controller.verify_instruction_generation()
            elif cmd == 'test':
                controller.send_motor_command()
            elif cmd == 'init':
                controller.send_init_command()
            elif cmd == 'status':
                print("\n当前电机角度 (ID 1-23):")
                for i in range(0, controller.num_motors, 4):
                    row = []
                    for j in range(4):
                        idx = i + j
                        if idx < controller.num_motors:
                            motor_id = idx + 1  # 显示ID从1开始
                            angle = controller.motor_angles[idx]
                            hex_angle = f"{angle & 0xFF:02X} {(angle >> 8) & 0xFF:02X}"
                            row.append(f"电机{motor_id:2d}: {angle:4d} ({hex_angle})")
                    print("  ".join(row))
            elif cmd == 'reset':
                if controller.reset_to_example():
                    print("已重置到示例指令的角度")
            elif cmd.startswith('set '):
                try:
                    parts = cmd.split()
                    if len(parts) == 3:
                        motor_id = int(parts[1])
                        angle = int(parts[2])
                        if controller.set_motor_angle(motor_id, angle):
                            print(f"电机 {motor_id} 已设置为角度 {angle}")
                except ValueError:
                    print("格式错误: set [id] [angle]")
                    print("注意：电机ID从1开始（1-23）")
            elif cmd.startswith('multi '):
                try:
                    parts = cmd.split()
                    if len(parts) >= 3 and len(parts) % 2 == 1:
                        motor_dict = {}
                        for i in range(1, len(parts), 2):
                            motor_id = int(parts[i])
                            angle = int(parts[i+1])
                            motor_dict[motor_id] = angle
                        
                        if controller.set_multiple_motors(motor_dict):
                            print(f"已设置 {len(motor_dict)} 个电机")
                except ValueError:
                    print("格式错误: multi id1 angle1 id2 angle2 ...")
                    print("注意：电机ID从1开始（1-23）")
            elif cmd.startswith('all '):
                try:
                    parts = cmd.split()
                    if len(parts) == 2:
                        angle = int(parts[1])
                        if controller.set_all_motors(angle):
                            print(f"所有电机已设置为角度 {angle}")
                except ValueError:
                    print("格式错误: all [angle]")
            else:
                print("未知命令")
    
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    finally:
        controller.disconnect()
        print("\n程序结束")

if __name__ == "__main__":
    main()