#include "board.h"

/**
	*	@brief		外设时钟初始化
	*	@param		无
	*	@retval		无
	*/
void clock_init(void)
{
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);	//使能GPIOA端口时钟
}

/**
	*	@brief		gpio引脚初始化
	*	@param		无
	*	@retval		无
	*/
void gpio_init(void)
{
/**************************************************************
	*	PA5接En（闭环驱动板屏幕上的En选项选择L或Hold）
	*	PA6接Stp
	*	PA7接Dir
***************************************************************/
 GPIO_InitTypeDef  GPIO_InitStructure;
 GPIO_InitStructure.GPIO_Pin = GPIO_Pin_5 | GPIO_Pin_6 | GPIO_Pin_7;
 GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;
 GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
 GPIO_Init(GPIOA, &GPIO_InitStructure);
 GPIO_ResetBits(GPIOA, GPIO_Pin_5 | GPIO_Pin_6 | GPIO_Pin_7);
}

/**
	*	@brief		板载初始化
	*	@param		无
	*	@retval		无
	*/
void board_init(void)
{
	clock_init();	/* 开启外设时钟 */
	gpio_init();	/* 初始化GPIO */
}
