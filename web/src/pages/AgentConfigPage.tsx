import { useEffect, useState } from 'react'
import { Button, Card, Form, Input, Modal, Slider, Space, Typography, message } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import { agentConfigApi, type AgentConfig } from '@/api/agentConfig'

const { Paragraph } = Typography

export default function AgentConfigPage() {
  const [form] = Form.useForm<AgentConfig>()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  // 提示词优化
  const [optimizing, setOptimizing] = useState(false)
  const [optimizeOpen, setOptimizeOpen] = useState(false)
  const [optimized, setOptimized] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await agentConfigApi.get()
      form.setFieldsValue(data)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await agentConfigApi.update(values)
      message.success('已保存')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const onOptimize = async () => {
    const raw = (form.getFieldValue('system_prompt') || '').trim()
    if (!raw) {
      message.warning('请先填写提示词')
      return
    }
    setOptimizing(true)
    try {
      const { data } = await agentConfigApi.optimizePrompt(raw)
      setOptimized(data.optimized)
      setOptimizeOpen(true)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setOptimizing(false)
    }
  }

  const onAdopt = () => {
    form.setFieldsValue({ system_prompt: optimized })
    setOptimizeOpen(false)
    message.success('已采纳，记得点保存')
  }

  return (
    <div className="fluid-narrow">
      <Card title="Agent 配置" loading={loading}>
        <Form form={form} layout="vertical">
          <Form.Item
            label={
              <Space>
                <span>系统提示词（人设 / 风格）</span>
                <Button
                  size="small"
                  type="link"
                  icon={<ThunderboltOutlined />}
                  loading={optimizing}
                  onClick={onOptimize}
                  style={{ padding: 0 }}
                >
                  优化
                </Button>
              </Space>
            }
            name="system_prompt"
            extra="给 AI 设定固定的人设、语气或回答风格，每次对话都会注入。点「优化」可让 AI 帮你润色"
          >
            <Input.TextArea
              autoSize={{ minRows: 4, maxRows: 10 }}
              placeholder="例如：你是一个简洁、专业的技术助手，回答尽量给出可运行的代码示例。"
            />
          </Form.Item>

          <Form.Item label="温度（创造性）" name="temperature">
            <Slider min={0} max={2} step={0.1} marks={{ 0: '严谨', 1: '平衡', 2: '发散' }} />
          </Form.Item>

          <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginTop: 4 }}>
            想开关知识库 / 记忆 / 联网等工具，请到「工具配置」页统一管理。
          </Typography.Paragraph>

          <Button type="primary" loading={saving} onClick={onSave}>
            保存
          </Button>
        </Form>
      </Card>

      <Modal
        title="优化后的提示词"
        open={optimizeOpen}
        onCancel={() => setOptimizeOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setOptimizeOpen(false)}>
            放弃
          </Button>,
          <Button key="adopt" type="primary" onClick={onAdopt}>
            采纳
          </Button>,
        ]}
        width={680}
      >
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          采纳后会填入提示词输入框，需再点「保存」才会生效。
        </Paragraph>
        <Input.TextArea
          value={optimized}
          onChange={(e) => setOptimized(e.target.value)}
          autoSize={{ minRows: 6, maxRows: 16 }}
        />
      </Modal>
    </div>
  )
}
