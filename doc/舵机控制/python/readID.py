import serial
import time

# 待发送的十六进制数据列表（字符串格式）
hex_data = [
    "FF FF 00 02 07 09",
    "FF FF 01 02 07 0A",
    "FF FF 02 02 07 0B",
    "FF FF 03 02 07 0C",
    "FF FF 04 02 07 0D",
    "FF FF 05 02 07 0E",
    "FF FF 06 02 07 0F",
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
    "FF FF 11 02 07 1A",
    "FF FF 12 02 07 1B",
    "FF FF 13 02 07 1C",
    "FF FF 14 02 07 1D",
    "FF FF 15 02 07 1E",
    "FF FF 16 02 07 1F"
]

def analyze_response(data_hex, expected_id=None):
    """分析响应数据"""
    try:
        data_bytes = bytes.fromhex(data_hex.replace(" ", ""))
        print(f"  原始响应 ({len(data_bytes)}字节): {data_hex}")
        
        # 尝试查找FF FF模式
        for i in range(len(data_bytes) - 1):
            if data_bytes[i] == 0xFF and data_bytes[i+1] == 0xFF:
                print(f"    在位置{i}找到FF FF")
                # 检查是否有足够的字节来提取ID
                if i + 2 < len(data_bytes):
                    id_byte = data_bytes[i+2]
                    print(f"    提取到ID: {id_byte}")
                    return id_byte
        
        # 如果没有找到FF FF，尝试其他模式
        print(f"    未找到FF FF模式")
        return None
    except:
        return None

def main():
    # 串口配置
    port = 'COM32'
    baudrate = 115200
    
    try:
        # 打开串口
        ser = serial.Serial(port, baudrate, timeout=0.1)
        print(f"串口 {port} 已打开，波特率 {baudrate}")
        print(f"将发送 {len(hex_data)} 条数据（ID 0-{len(hex_data)-1}）")
        print("-" * 50)
        
        # 清空接收缓冲区
        if ser.in_waiting > 0:
            ser.read(ser.in_waiting)
        
        # 存储接收到的ID
        received_ids = []
        
        # 发送数据并立即接收
        print("\n开始发送并接收数据：")
        print("-" * 50)
        
        for i, hex_str in enumerate(hex_data):
            try:
                # 转换为字节并发送
                data_bytes = bytes.fromhex(hex_str.replace(" ", ""))
                print(f"\n发送 ID {i:2d}: {hex_str}")
                
                # 发送数据
                ser.write(data_bytes)
                ser.flush()  # 确保数据已发送
                
                # 等待响应（增加等待时间）
                time.sleep(0.01)  # 100ms等待响应
                
                # 读取响应
                if ser.in_waiting > 0:
                    response = ser.read(ser.in_waiting)
                    
                    if response:
                        # 转换为十六进制字符串
                        hex_str_resp = response.hex().upper()
                        formatted_resp = ' '.join([hex_str_resp[i:i+2] for i in range(0, len(hex_str_resp), 2)])
                        
                        print(f"  收到响应: {formatted_resp}")
                        
                        # 分析响应
                        id_found = analyze_response(hex_str_resp, i)
                        if id_found is not None:
                            if id_found not in received_ids:
                                received_ids.append(id_found)
                            print(f"  ✓ 成功接收 ID {id_found}")
                        else:
                            print(f"  ✗ 未提取到有效ID")
                
                else:
                    print(f"  ⚠ 未收到响应")
                
                # 短暂延时，避免发送过快
                time.sleep(0.1)
                
            except Exception as e:
                print(f"发送/接收 ID {i} 失败: {e}")
                continue
        
        # 额外等待一段时间，以防有延迟的响应
        print(f"\n等待额外延迟响应...")
        extra_start = time.time()
        extra_timeout = 1  # 3秒
        
        while time.time() - extra_start < extra_timeout:
            if ser.in_waiting > 0:
                response = ser.read(ser.in_waiting)
                if response:
                    hex_str_resp = response.hex().upper()
                    formatted_resp = ' '.join([hex_str_resp[i:i+2] for i in range(0, len(hex_str_resp), 2)])
                    print(f"  延迟响应: {formatted_resp}")
                    
                    # 分析延迟响应
                    id_found = analyze_response(hex_str_resp)
                    if id_found is not None and id_found not in received_ids:
                        received_ids.append(id_found)
                        print(f"  ✓ 从延迟响应中提取到 ID {id_found}")
            
            time.sleep(0.05)
        
        # 显示最终统计
        print("\n" + "=" * 50)
        print("最终接收统计：")
        print(f"期望接收数据数量: {len(hex_data)}")
        print(f"实际接收数据数量: {len(received_ids)}")
        
     
        
        print("=" * 50)
        
        ser.close()
        print("\n串口已关闭")
        
    except serial.SerialException as e:
        print(f"无法打开串口 {port}: {e}")
    except KeyboardInterrupt:
        print("\n程序被用户中断")
        if 'ser' in locals() and ser.is_open:
            ser.close()
    except Exception as e:
        print(f"程序运行出错: {e}")
        import traceback
        traceback.print_exc()
        if 'ser' in locals() and ser.is_open:
            ser.close()

def test_response_pattern():
    """测试响应模式"""
    print("\n测试响应模式分析：")
    test_responses = [
        "FF FF 03 03 A7 00",      # 您之前收到的
        "AD FF FF 0B 03 A7",      # 您之前收到的
        "00 B5 FF FF 0E 03",      # 您之前收到的
        "A7 00 B8 FF FF 15",      # 您之前收到的
    ]
    
    for resp in test_responses:
        print(f"\n分析: {resp}")
        analyze_response(resp)

if __name__ == "__main__":
    # 先测试响应模式分析
    test_response_pattern()
    
    # 运行主程序
    main()