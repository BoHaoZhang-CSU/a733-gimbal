
data_without_checksum = "FF FF 0f 04 05 00 00"
# data_without_checksum = "FF FF FE 32 FE 01 BB 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
data_bytes = bytes.fromhex(data_without_checksum)

print(f"输入数据长度: {len(data_bytes)} 字节")

# 根据算法，从第3字节开始到最后一个字节都要参与计算
# 因为最后一个字节是数据，不是校验和
calc_range = data_bytes[2:]  # 从FE到最后一个CD
print(f"计算范围长度: {len(calc_range)} 字节")

checksum = sum(calc_range) & 0xFF
print(f"计算出的校验和: {data_without_checksum} {checksum:02X}")

# 验证：如果加上这个校验和，完整的50字节数据的校验和应该正确
full_data = data_bytes + bytes([checksum])
calc_range_full = full_data[2:49]  # 索引2到48
calc_checksum_full = sum(calc_range_full) & 0xFF
print(f"完整数据校验和验证: 计算=0x{calc_checksum_full:02X}, 实际=0x{checksum:02X}, 匹配={calc_checksum_full == checksum}")