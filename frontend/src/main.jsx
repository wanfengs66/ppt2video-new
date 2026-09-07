import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './styles/global.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: theme.darkAlgorithm,
          token: {
            colorPrimary: '#fdf1e1',
            colorInfo: '#4ab5e0',
            colorBgBase: '#0b1110',
            colorBgContainer: '#131b18',
            colorBgElevated: '#1a241f',
            colorBorder: 'rgba(253,241,225,0.12)',
            colorBorderSecondary: 'rgba(253,241,225,0.08)',
            colorText: '#fdf1e1',
            colorTextSecondary: 'rgba(253,241,225,0.62)',
            colorTextTertiary: 'rgba(253,241,225,0.38)',
            colorSuccess: '#7ddba0',
            borderRadius: 10,
            fontSize: 14,
          },
          components: {
            Button: {
              primaryColor: '#111411',
              primaryShadow: '0 16px 34px rgba(0,0,0,0.18)',
            },
            Layout: {
              siderBg: '#131b18',
              bodyBg: 'transparent',
            },
            Card: {
              colorBgContainer: '#131b18',
            },
            Table: {
              colorBgContainer: 'transparent',
              headerBg: '#1a241f',
            },
            Modal: {
              contentBg: '#131b18',
              headerBg: '#131b18',
            },
            Progress: {
              remainingColor: 'rgba(253,241,225,0.1)',
            },
          },
        }}
      >
        <App />
      </ConfigProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
