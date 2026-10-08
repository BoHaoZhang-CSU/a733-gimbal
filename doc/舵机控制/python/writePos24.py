import serial
import time

class MotorController24:
    def __init__(self, port='COM32', baudrate=115200):
        """初始化24电机控制器"""
        self.port = port
        self.baudrate = baudrate
        self.num_motors = 24  # 总共24个电机
        self.ser = None
        
        # 初始化指令
        self.init_command = bytes.fromhex("FF FF FE 03 02 01 04")
        
        # 原始23电机示例指令
        self.original_23_instruction = bytes.fromhex("FF FF FE 32 FE 01 BB 01 10 01 64 01 CD 02 72 02 0F 02 D5 00 DA 01 BE 01 D6 01 CD 01 C1 02 EA 02 CF 00 B9 01 D3 01 D3 01 CD 01 CD 01 CD 01 82 00 00 00 00 01 CD 63")
        
        # 分析原始指令中的角度顺序
        self.analyze_angle_order()
        
        # 初始化电机角度
        self.motor_angles = self.initialize_motor_angles()
    
    def analyze_angle_order(self):
        """分析原始指令中的角度字节顺序"""
        print("\n分析原始23电机指令的角度顺序:")
        
        example_bytes = self.original_23_instruction
        
        # 查看前几个电机的角度数据
        print("前3个电机的角度数据:")
        for i in range(3):
            start_idx = 7 + i * 2
            byte1 = example_bytes[start_idx]     # 第1个字节
            byte2 = example_bytes[start_idx + 1]  # 第2个字节
            
            # 尝试两种解码方式
            angle_method1 = (byte2 << 8) | byte1  # 假设byte2是高字节，byte1是低字节
            angle_method2 = (byte1 << 8) | byte2  # 假设byte1是高字节，byte2是低字节
            
            print(f"电机{i+1}: 字节[{byte1:02X} {byte2:02X}]")
            print(f"  方式1 (byte2高byte1低): {angle_method1}")
            print(f"  方式2 (byte1高byte2低): {angle_method2}")
            
            # 查看哪个角度值更合理（0-1023范围内）
            if 0 <= angle_method1 <= 1023 and not (0 <= angle_method2 <= 1023):
                print(f"  → 方式1更合理 (在0-1023范围内)")
            elif 0 <= angle_method2 <= 1023 and not (0 <= angle_method1 <= 1023):
                print(f"  → 方式2更合理 (在0-1023范围内)")
            elif 0 <= angle_method1 <= 1023 and 0 <= angle_method2 <= 1023:
                print(f"  → 两种方式都在范围内，需要进一步判断")
        
        # 检查特殊电机（电机21角度为0）
        print("\n检查电机21（应接近0）:")
        start_idx = 7 + 20 * 2  # 电机21（索引20）
        byte1 = example_bytes[start_idx]
        byte2 = example_bytes[start_idx + 1]
        angle_method1 = (byte2 << 8) | byte1
        angle_method2 = (byte1 << 8) | byte2
        print(f"字节: [{byte1:02X} {byte2:02X}]")
        print(f"方式1: {angle_method1}")
        print(f"方式2: {angle_method2}")
        
        # 确定正确的字节顺序
        if byte1 == 0x00 and byte2 == 0x00:  # 两个字节都是0
            self.angle_high_first = False  # 高字节在前？
        elif angle_method1 == 0:
            print("→ 方式1得到角度0 (byte2是高字节)")
            self.angle_high_first = False  # byte2是高字节
        elif angle_method2 == 0:
            print("→ 方式2得到角度0 (byte1是高字节)")
            self.angle_high_first = True   # byte1是高字节
    
    def initialize_motor_angles(self):
        """初始化24个电机的角度"""
        example_bytes = self.original_23_instruction
        angles = []
        
        # 解析前23个电机的角度
        for i in range(23):
            start_idx = 7 + i * 2
            byte1 = example_bytes[start_idx]
            byte2 = example_bytes[start_idx + 1]
            
            # 根据分析结果选择解码方式
            if hasattr(self, 'angle_high_first'):
                if self.angle_high_first:
                    angle = (byte1 << 8) | byte2  # byte1是高字节
                else:
                    angle = (byte2 << 8) | byte1  # byte2是高字节
            else:
                # 默认尝试两种方式，选择合理的值
                angle1 = (byte2 << 8) | byte1
                angle2 = (byte1 << 8) | byte2
                
                if 0 <= angle1 <= 1023:
                    angle = angle1
                elif 0 <= angle2 <= 1023:
                    angle = angle2
                else:
                    angle = 512  # 默认中间值
            
            angles.append(angle)
        
        # 第24个电机
        angles.append(512)
        
        print(f"\n初始化完成，前5个电机角度:")
        for i in range(min(5, len(angles))):
            print(f"  电机{i+1}: {angles[i]}")
        
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
    
    def disconnect(self):
        """断开串口连接"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("串口已关闭")
    
    def send_init_command(self):
        """发送初始化指令"""
        if not self.ser or not self.ser.is_open:
            print("错误：串口未连接")
            return False
        
        try:
            print(f"发送初始化指令: {self.init_command.hex().upper()}")
            self.ser.write(self.init_command)
            self.ser.flush()
            time.sleep(0.1)
            
            self.read_response()
            return True
        except Exception as e:
            print(f"发送初始化指令时出错: {e}")
            return False
    
    def calculate_checksum(self, data_bytes):
        """计算校验和：从第3字节开始到最后一个字节求和，取低8位"""
        if len(data_bytes) < 3:
            return 0
        
        calc_range = data_bytes[2:]  # 索引2开始到结束
        checksum = sum(calc_range) & 0xFF
        return checksum
    
    def angle_to_bytes_different_orders(self, angle):
        """返回两种可能的字节顺序"""
        if angle < 0:
            angle = 0
        elif angle > 1023:
            angle = 1023
        
        # 方式1: 高字节在前，低字节在后
        high_byte1 = (angle >> 8) & 0xFF
        low_byte1 = angle & 0xFF
        
        # 方式2: 低字节在前，高字节在后
        low_byte2 = angle & 0xFF
        high_byte2 = (angle >> 8) & 0xFF
        
        return {
            'high_first': (high_byte1, low_byte1),  # 高字节在前
            'low_first': (low_byte2, high_byte2)    # 低字节在前
        }
    
    def create_motor_command(self, motor_angles, byte_order='auto'):
        """创建电机控制指令，支持不同的字节顺序"""
        if len(motor_angles) != self.num_motors:
            print(f"错误：需要{self.num_motors}个电机角度，但提供了{len(motor_angles)}个")
            return None
        
        # 确定字节顺序
        if byte_order == 'auto':
            # 基于分析结果选择
            if hasattr(self, 'angle_high_first'):
                order = 'high_first' if self.angle_high_first else 'low_first'
            else:
                order = 'low_first'  # 默认使用低字节在前
        else:
            order = byte_order
        
        print(f"创建指令 - 使用字节顺序: {order}")
        
        # 构建指令头（修改第4字节为0x34，对应24电机）
        header = list(self.original_23_instruction[:7])
        header[3] = 0x34  # 修改为24电机的长度
        
        data_list = []
        data_list.extend(header)
        
        # 添加电机角度数据
        for angle in motor_angles:
            bytes_dict = self.angle_to_bytes_different_orders(angle)
            if order == 'high_first':
                byte1, byte2 = bytes_dict['high_first']
            else:  # low_first
                byte1, byte2 = bytes_dict['low_first']
            
            data_list.append(byte1)
            data_list.append(byte2)
        
        # 计算校验和
        data_bytes = bytes(data_list)
        checksum = self.calculate_checksum(data_bytes)
        
        # 完整指令
        full_command = data_bytes + bytes([checksum])
        
        return full_command
    
    def send_motor_command_with_order(self, byte_order='auto'):
        """使用指定字节顺序发送指令"""
        if not self.ser or not self.ser.is_open:
            print("错误：串口未连接")
            return False
        
        try:
            command = self.create_motor_command(self.motor_angles, byte_order)
            if command is None:
                return False
            
            print(f"\n发送指令 (字节顺序: {byte_order}):")
            self.print_command_details(command)
            
            self.ser.write(command)
            self.ser.flush()
            time.sleep(0.1)
            
            self.read_response()
            return True
            
        except Exception as e:
            print(f"发送指令时出错: {e}")
            return False
    
    def send_original_23_command(self):
        """发送原始23电机指令"""
        if not self.ser or not self.ser.is_open:
            print("错误：串口未连接")
            return False
        
        try:
            command = self.original_23_instruction
            
            print("\n发送原始23电机指令:")
            print(f"指令: {command.hex().upper()}")
            print(f"长度: {len(command)}字节")
            
            # 显示前几个电机的角度
            print("\n指令中的角度数据:")
            for i in range(3):
                start_idx = 7 + i * 2
                byte1 = command[start_idx]
                byte2 = command[start_idx + 1]
                angle1 = (byte2 << 8) | byte1  # byte2高，byte1低
                angle2 = (byte1 << 8) | byte2  # byte1高，byte2低
                print(f"电机{i+1}: [{byte1:02X} {byte2:02X}] -> 方式1:{angle1} 方式2:{angle2}")
            
            self.ser.write(command)
            self.ser.flush()
            time.sleep(0.1)
            
            self.read_response()
            return True
            
        except Exception as e:
            print(f"发送原始指令时出错: {e}")
            return False
    
    def print_command_details(self, command):
        """打印指令详细信息"""
        hex_str = command.hex().upper()
        formatted = ' '.join([hex_str[i:i+2] for i in range(0, len(hex_str), 2)])
        
        print(f"指令: {formatted}")
        print(f"长度: {len(command)}字节")
        print(f"头部: {' '.join([f'{b:02X}' for b in command[:7]])}")
        
        # 显示角度数据
        print("\n指令中的角度数据:")
        for i in range(min(3, self.num_motors)):
            start_idx = 7 + i * 2
            if start_idx + 1 < len(command):
                byte1 = command[start_idx]
                byte2 = command[start_idx + 1]
                print(f"电机{i+1}: [{byte1:02X} {byte2:02X}]")
        
        # 校验和
        calc_checksum = self.calculate_checksum(command[:-1])
        actual_checksum = command[-1]
        print(f"\n校验和: 计算={calc_checksum:02X}, 实际={actual_checksum:02X}")
        print("-" * 60)
    
    def set_motor_angle(self, motor_id, angle, byte_order='auto'):
        """设置单个电机角度"""
        if motor_id < 1 or motor_id > self.num_motors:
            print(f"错误：电机ID {motor_id} 超出范围 (1-{self.num_motors})")
            return False
        
        array_index = motor_id - 1
        old_angle = self.motor_angles[array_index]
        self.motor_angles[array_index] = angle
        
        print(f"电机 {motor_id}: {old_angle} → {angle}")
        return self.send_motor_command_with_order(byte_order)
    
    def test_angle_encoding(self, angle=512):
        """测试角度编码"""
        print(f"\n测试角度编码: {angle}")
        
        bytes_dict = self.angle_to_bytes_different_orders(angle)
        
        print(f"高字节在前: {bytes_dict['high_first'][0]:02X} {bytes_dict['high_first'][1]:02X}")
        print(f"低字节在前: {bytes_dict['low_first'][0]:02X} {bytes_dict['low_first'][1]:02X}")
        
        # 解码测试
        high_first_angle = (bytes_dict['high_first'][0] << 8) | bytes_dict['high_first'][1]
        low_first_angle = (bytes_dict['low_first'][1] << 8) | bytes_dict['low_first'][0]
        
        print(f"解码测试:")
        print(f"  高字节在前解码: {high_first_angle}")
        print(f"  低字节在前解码: {low_first_angle}")
    
    def test_different_byte_orders(self):
        """测试不同的字节顺序"""
        print("\n" + "="*60)
        print("测试不同的字节顺序")
        print("="*60)
        
        # 测试高字节在前
        print("\n1. 测试高字节在前:")
        success1 = self.send_motor_command_with_order('high_first')
        
        time.sleep(0.5)
        
        # 测试低字节在前
        print("\n2. 测试低字节在前:")
        success2 = self.send_motor_command_with_order('low_first')
        
        return success1 or success2
    
    def read_response(self):
        """读取串口返回数据"""
        try:
            time.sleep(0.1)
            if self.ser.in_waiting > 0:
                response = self.ser.read(self.ser.in_waiting)
                if response:
                    hex_str = response.hex().upper()
                    formatted = ' '.join([hex_str[i:i+2] for i in range(0, len(hex_str), 2)])
                    print(f"收到响应: {formatted}")
                    return response
        except:
            pass
        return None
    
    def analyze_original_instruction_thoroughly(self):
        """彻底分析原始指令"""
        print("\n" + "="*60)
        print("彻底分析原始23电机指令")
        print("="*60)
        
        cmd = self.original_23_instruction
        
        print(f"指令总长度: {len(cmd)}字节")
        print(f"完整指令: {cmd.hex().upper()}")
        
        # 分析头部
        print("\n指令头部分析:")
        headers = ["帧头1", "帧头2", "设备地址", "数据长度", "命令1", "命令2", "参数"]
        for i in range(7):
            print(f"  字节{i+1} ({headers[i]}): {cmd[i]:02X}")
        
        # 分析角度数据
        print("\n23个电机角度分析:")
        for i in range(23):
            start_idx = 7 + i * 2
            byte1 = cmd[start_idx]
            byte2 = cmd[start_idx + 1]
            
            # 两种解码方式
            angle_low_first = (byte2 << 8) | byte1  # byte2高，byte1低
            angle_high_first = (byte1 << 8) | byte2  # byte1高，byte2低
            
            # 判断哪个更合理
            reasonable_low = 0 <= angle_low_first <= 1023
            reasonable_high = 0 <= angle_high_first <= 1023
            
            note = ""
            if i == 20:  # 电机21
                note = " (应接近0)"
            
            print(f"电机{i+1:2d}: [{byte1:02X} {byte2:02X}]", end="")
            print(f" → 低前:{angle_low_first:4d}", end="")
            if reasonable_low:
                print(" ✓", end="")
            else:
                print(" ✗", end="")
            
            print(f" 高前:{angle_high_first:4d}", end="")
            if reasonable_high:
                print(" ✓", end="")
            else:
                print(" ✗", end="")
            
            print(note)

def main():
    controller = MotorController24(port='COM32', baudrate=115200)
    
    if not controller.connect():
        return
    
    try:
        print("\n" + "="*60)
        print("24电机控制器 - 字节顺序调试版")
        print("="*60)
        
        # 初始化
        print("\n1. 发送初始化指令...")
        controller.send_init_command()
        
        # 分析原始指令
        controller.analyze_original_instruction_thoroughly()
        
        # 测试原始23指令
        print("\n2. 测试原始23电机指令...")
        controller.send_original_23_command()
        
        print("\n3. 测试角度编码...")
        controller.test_angle_encoding(512)
        
        print("\n" + "="*60)
        print("命令说明:")
        print("  test23      - 测试原始23电机指令")
        print("  byte_test   - 测试不同字节顺序")
        print("  high        - 使用高字节在前发送")
        print("  low         - 使用低字节在前发送")
        print("  set [id] [angle] - 设置单个电机")
        print("  encode [angle] - 测试角度编码")
        print("  analyze     - 分析原始指令")
        print("  status      - 显示状态")
        print("  init        - 重新初始化")
        print("  exit        - 退出")
        print("="*60)
        
        while True:
            user_input = input("\n请输入命令: ").strip()
            
            if not user_input:
                continue
                
            cmd = user_input.lower()
            
            if cmd == 'exit':
                break
            elif cmd == 'test23':
                controller.send_original_23_command()
            elif cmd == 'byte_test':
                controller.test_different_byte_orders()
            elif cmd == 'high':
                controller.send_motor_command_with_order('high_first')
            elif cmd == 'low':
                controller.send_motor_command_with_order('low_first')
            elif cmd == 'analyze':
                controller.analyze_original_instruction_thoroughly()
            elif cmd == 'init':
                controller.send_init_command()
            elif cmd == 'status':
                print("\n当前24个电机角度:")
                for i in range(0, controller.num_motors, 6):
                    row = []
                    for j in range(6):
                        idx = i + j
                        if idx < controller.num_motors:
                            motor_id = idx + 1
                            angle = controller.motor_angles[idx]
                            row.append(f"电机{motor_id:2d}: {angle:4d}")
                    print("  ".join(row))
            elif cmd.startswith('set '):
                try:
                    parts = cmd.split()
                    if len(parts) == 3:
                        motor_id = int(parts[1])
                        angle = int(parts[2])
                        
                        # 先测试低字节在前
                        print("尝试低字节在前...")
                        if controller.set_motor_angle(motor_id, angle, 'low_first'):
                            print("使用低字节在前发送")
                        
                        time.sleep(0.5)
                        
                        # 再测试高字节在前
                        print("尝试高字节在前...")
                        if controller.set_motor_angle(motor_id, angle, 'high_first'):
                            print("使用高字节在前发送")
                            
                except ValueError:
                    print("格式错误: set [id] [angle]")
            elif cmd.startswith('encode '):
                try:
                    parts = cmd.split()
                    if len(parts) == 2:
                        angle = int(parts[1])
                        controller.test_angle_encoding(angle)
                except ValueError:
                    print("格式错误: encode [angle]")
            else:
                print("未知命令")
    
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    finally:
        controller.disconnect()
        print("\n程序结束")

if __name__ == "__main__":
    main()