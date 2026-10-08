#include <Arduino.h>

#define S_RXD 18
#define S_TXD 19
// 电机控制类
class MotorController23 {
private:
  HardwareSerial* serialPort;
  int numMotors;

  // 初始化指令
  byte initCommand[7] = { 0xFF, 0xFF, 0xFE, 0x03, 0x02, 0x01, 0x04 };

  // 固定头
  byte headerFixed[7] = { 0xFF, 0xFF, 0xFE, 0x32, 0xFE, 0x01, 0xBB };

  // 电机角度数组 (0-1023)
  int motorAngles[23];

  // 计算校验和
  byte calculateChecksum(byte* data, int length) {
    if (length < 3) return 0;

    unsigned int sum = 0;
    // 从第3字节开始（索引2）到最后一个数据字节
    for (int i = 2; i < length; i++) {
      sum += data[i];
    }
    return sum & 0xFF;
  }

  // 角度转换为字节（小端序）
  void angleToBytes(int angle, byte* low, byte* high) {
    if (angle < 0) angle = 0;
    if (angle > 1023) angle = 1023;

    *low = (angle >> 8) & 0xFF;  // 高字节
    *high = angle & 0xFF;        // 低字节
  }

  // 解析串口命令
  void parseCommand(String cmd) {
    cmd.trim();
    cmd.toLowerCase();

    if (cmd.length() == 0) return;

    // 分割命令
    int spaceIndex1 = cmd.indexOf(' ');
    String command = cmd;
    String params = "";

    if (spaceIndex1 != -1) {
      command = cmd.substring(0, spaceIndex1);
      params = cmd.substring(spaceIndex1 + 1);
    }

    if (command == "set") {
      // 设置单个电机
      int spaceIndex2 = params.indexOf(' ');
      if (spaceIndex2 != -1) {
        String idStr = params.substring(0, spaceIndex2);
        String angleStr = params.substring(spaceIndex2 + 1);

        int motorId = idStr.toInt();
        int angle = angleStr.toInt();

        if (motorId >= 1 && motorId <= 23 && angle >= 0 && angle <= 1023) {
          setMotorAngle(motorId, angle);
          Serial.printf("电机 %d 已设置为角度 %d\n", motorId, angle);
        } else {
          Serial.println("错误：电机ID应为1-23，角度应为0-1023");
        }
      } else {
        Serial.println("格式错误: set [id] [angle]");
      }
    } else if (command == "multi") {
      // 设置多个电机
      bool success = true;
      String remaining = params;

      while (remaining.length() > 0) {
        int space1 = remaining.indexOf(' ');
        if (space1 == -1) {
          success = false;
          break;
        }

        String idStr = remaining.substring(0, space1);
        remaining = remaining.substring(space1 + 1);

        int space2 = remaining.indexOf(' ');
        String angleStr;
        if (space2 == -1) {
          angleStr = remaining;
          remaining = "";
        } else {
          angleStr = remaining.substring(0, space2);
          remaining = remaining.substring(space2 + 1);
        }

        int motorId = idStr.toInt();
        int angle = angleStr.toInt();

        if (motorId >= 1 && motorId <= 23 && angle >= 0 && angle <= 1023) {
          setMotorAngle(motorId, angle);
        } else {
          success = false;
          break;
        }
      }

      if (success) {
        sendMotorCommand();
        Serial.println("多个电机设置完成");
      } else {
        Serial.println("格式错误: multi id1 angle1 id2 angle2 ...");
      }
    } else if (command == "all") {
      // 设置所有电机
      if (params.length() > 0) {
        int angle = params.toInt();
        if (angle >= 0 && angle <= 1023) {
          setAllMotors(angle);
          Serial.printf("所有电机已设置为角度 %d\n", angle);
        } else {
          Serial.println("错误：角度应为0-1023");
        }
      } else {
        Serial.println("格式错误: all [angle]");
      }
    } else if (command == "status") {
      // 显示状态
      showStatus();
    } else if (command == "reset") {
      // 重置到初始状态
      resetToInitial();
      Serial.println("已重置到初始状态");
    } else if (command == "test") {
      // 测试发送指令
      sendMotorCommand();
      Serial.println("测试指令已发送");
    } else if (command == "init") {
      // 发送初始化指令
      sendInitCommand();
      Serial.println("初始化指令已发送");
    } else if (command == "help") {
      // 显示帮助
      showHelp();
    } else {
      Serial.println("未知命令，输入 'help' 查看帮助");
    }
  }

  // 显示帮助
  void showHelp() {
    Serial.println("\n===== 23电机控制系统 =====");
    Serial.println("电机ID: 1-23, 角度范围: 0-1023");
    Serial.println("\n可用命令:");
    Serial.println("  set [id] [angle]      - 设置单个电机角度");
    Serial.println("  multi id1 angle1 id2 angle2 ... - 设置多个电机");
    Serial.println("  all [angle]           - 设置所有电机到同一角度");
    Serial.println("  status                - 显示当前所有电机角度");
    Serial.println("  reset                 - 重置到初始状态 (0-900)");
    Serial.println("  test                  - 测试发送当前指令");
    Serial.println("  init                  - 发送初始化指令");
    Serial.println("  help                  - 显示此帮助信息");
    Serial.println("\n示例:");
    Serial.println("  set 1 512             # 设置电机1到角度512");
    Serial.println("  multi 1 300 2 600 3 900");
    Serial.println("  all 0                 # 所有电机复位到0");
    Serial.println("=========================");
  }

  // 显示状态
  void showStatus() {
    Serial.println("\n当前电机角度 (ID 1-23):");
    for (int i = 0; i < 23; i += 4) {
      String line = "";
      for (int j = 0; j < 4 && (i + j) < 23; j++) {
        int idx = i + j;
        int motorId = idx + 1;
        int angle = motorAngles[idx];
        byte low, high;
        angleToBytes(angle, &low, &high);

        line += "电机";
        if (motorId < 10) line += " ";
        line += String(motorId);
        line += ": ";
        line += String(angle);
        line += " (";
        line += String(high, HEX);
        line += String(low, HEX);
        line += ")";

        if (j < 3 && (i + j + 1) < 23) {
          line += "  ";
        }
      }
      Serial.println(line);
    }
  }

public:
  // 构造函数
  MotorController23(HardwareSerial* serial = &Serial1) {
    serialPort = serial;
    numMotors = 23;

    // 初始化电机角度为0-900
    for (int i = 0; i < 23; i++) {
      motorAngles[i] = (i * 40) % 901;  // 0-900之间的不同值
    }
  }

  // 初始化
  void begin(long baudrate = 115200) {
    serialPort->begin(baudrate, SERIAL_8N1, S_RXD, S_TXD);
    Serial.printf("串口已初始化，波特率: %d\n", baudrate);

    // 发送初始化指令
    sendInitCommand();

    // 显示帮助信息
    showHelp();
  }

  // 发送初始化指令
  void sendInitCommand() {
    serialPort->write(initCommand, sizeof(initCommand));
    delay(50);
    Serial.println("初始化指令已发送");
  }

  // 设置单个电机角度
  void setMotorAngle(int motorId, int angle) {
    if (motorId >= 1 && motorId <= numMotors) {
      if (angle < 0) angle = 0;
      if (angle > 1023) angle = 1023;

      motorAngles[motorId - 1] = angle;
    }
  }

  // 设置所有电机角度
  void setAllMotors(int angle) {
    if (angle < 0) angle = 0;
    if (angle > 1023) angle = 1023;

    for (int i = 0; i < numMotors; i++) {
      motorAngles[i] = angle;
    }
    sendMotorCommand();
  }

  // 重置到初始状态
  void resetToInitial() {
    for (int i = 0; i < numMotors; i++) {
      motorAngles[i] = (i * 40) % 901;
    }
    sendMotorCommand();
  }

  // 创建并发送电机控制指令
  void sendMotorCommand() {
    // 指令总长度: 7字节头 + 46字节角度数据 + 1字节校验和 = 54字节
    byte command[54];

    // 1. 复制固定头
    for (int i = 0; i < 7; i++) {
      command[i] = headerFixed[i];
    }

    // 2. 添加电机角度数据
    for (int i = 0; i < numMotors; i++) {
      byte low, high;
      angleToBytes(motorAngles[i], &low, &high);

      // 位置: 7 + i*2
      command[7 + i * 2] = low;   // 高字节在前
      command[8 + i * 2] = high;  // 低字节在后
    }

    // 3. 计算校验和
    byte checksum = calculateChecksum(command, 53);
    command[53] = checksum;

    // 4. 发送指令
    serialPort->write(command, sizeof(command));
    delay(50);

    // 5. 调试输出
    Serial.println("电机指令已发送:");
    Serial.print("HEX: ");
    for (int i = 0; i < sizeof(command); i++) {
      if (command[i] < 0x10) Serial.print("0");
      Serial.print(command[i], HEX);
      Serial.print(" ");
      if ((i + 1) % 16 == 0) Serial.println();
    }
    Serial.println();

    // 显示电机角度
    for (int i = 0; i < numMotors; i++) {
      if (i % 8 == 0) {
        if (i > 0) Serial.println();
        Serial.print("   ");
      }
      Serial.printf("M%02d:%4d ", i + 1, motorAngles[i]);
    }
    Serial.println();
  }

  // 处理串口输入
  void handleSerialInput() {
    if (Serial.available()) {
      String input = Serial.readStringUntil('\n');
      parseCommand(input);
    }
  }
};

// 全局电机控制器实例
MotorController23 motorController(&Serial1);  // 使用Serial1控制电机

void setup() {
  // 初始化调试串口
  Serial.begin(115200);
  Serial.println("\n===== ESP32 23电机控制系统 =====");

  // 初始化电机控制器
  motorController.begin(115200);
}

void loop() {
  // 处理串口输入
  motorController.handleSerialInput();

  motorController.setAllMotors(0);
  delay(1000);
  motorController.setAllMotors(200);
  delay(1000);
}