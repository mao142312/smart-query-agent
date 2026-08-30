export default function MaintenancePage() {
  return (
    <main className="maintenance">
      <div className="glow glowOne" />
      <div className="glow glowTwo" />
      <section className="panel">
        <div className="brand"><span>数</span><strong>知数</strong></div>
        <div className="status"><i /> 产品迭代中</div>
        <p className="eyebrow">SMART DATA · NEXT RELEASE</p>
        <h1>我们正在准备<br /><em>更好用的智能问数体验</em></h1>
        <p className="description">网站现已暂停访问。团队正在升级数据连接、分析能力与交互体验，新版本准备完成后将在这里重新上线。</p>
        <div className="divider" />
        <footer><span>感谢你的耐心等待</span><small>知数团队</small></footer>
      </section>
    </main>
  );
}
