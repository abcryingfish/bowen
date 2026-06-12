/**
 * 万花筒写轮眼 Canvas（绘制逻辑与 deepseek_html_20260522_fe576f.html 内脚本一致）。
 * 画布逻辑分辨率 600x600，由 CSS 缩放入 .edge-float-hud（外层 52px 不变）。
 */
(function () {
    "use strict";
    // ----- 获取画布元素 -----
    const canvas = document.getElementById("edge-float-mangekyo-canvas");
    if (!canvas) {
        return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
        return;
    }

    // 定义尺寸 (固定600x600 高清绘制)
        const SIZE = 600;
        canvas.width = SIZE;
        canvas.height = SIZE;
        let centerX = SIZE / 2;
        let centerY = SIZE / 2;
        let radius = SIZE * 0.46;   // 主半径范围 ≈ 276px
        
        // 动态变量
        let animationId = null;
        let startTime = null;
        let globalRotation = 0;      // 整体旋转弧度
        
        // 动画参数（旋转速度 rad/ms）
        let speed = 0.0044;          // 旋转速度 (rad/ms)，较初版再快一倍
        let pulseFactor = 0;          // 脉动系数用于瞳孔和额外特效

        // 系统「减少动态效果」时放慢转速，仍保持转动（避免被误认为卡死）
        try {
            const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            if (reduceMotion) {
                speed *= 0.22;
            }
        } catch (_) {
            /* ignore */
        }

        /** 悬停浮标时转速 ×7（相对当前基准，含减少动态效果后的基准） */
        const baseSpeed = speed;
        const hud = document.getElementById("edge-float-hud");
        if (hud) {
            hud.addEventListener("mouseenter", () => {
                speed = baseSpeed * 7;
            });
            hud.addEventListener("mouseleave", () => {
                speed = baseSpeed;
            });
        }

        // 辅助函数：将角度转弧度 (便于调试)
        function degToRad(deg) {
            return (deg * Math.PI) / 180;
        }
        
        // ---------- 绘制万花筒写轮眼核心图案 ----------
        // 由于需要极致的万花筒视觉，利用分层对称 + 独特刃纹 + 六芒星咒印风格
        
        // 1. 绘制背景：猩红到暗黑的邪瞳基底
        function drawBackground() {
            const grad = ctx.createRadialGradient(centerX, centerY, 10, centerX, centerY, radius + 20);
            grad.addColorStop(0, '#8b0000');      // 深红中心
            grad.addColorStop(0.4, '#5e0000');
            grad.addColorStop(0.7, '#2f0000');
            grad.addColorStop(1, '#0a0000');
            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, SIZE, SIZE);
            
            // 增加暗色网格血丝感 (径向细线)
            ctx.save();
            ctx.globalCompositeOperation = 'lighter';
            ctx.beginPath();
            for (let i = 0; i < 36; i++) {
                const angle = (i / 36) * Math.PI * 2;
                const x1 = centerX + Math.cos(angle) * 20;
                const y1 = centerY + Math.sin(angle) * 20;
                const x2 = centerX + Math.cos(angle) * (radius + 15);
                const y2 = centerY + Math.sin(angle) * (radius + 15);
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.strokeStyle = `rgba(100, 20, 10, ${0.08 + Math.sin(angle * 3) * 0.04})`;
                ctx.lineWidth = 1.2;
                ctx.stroke();
            }
            ctx.restore();
        }
        
        // 2. 绘制外圈结界纹路 (复杂几何圆环 + 勾玉残影)
        function drawOuterRings() {
            ctx.save();
            ctx.shadowBlur = 0;
            for (let i = 0; i < 3; i++) {
                const ringRad = radius - i * 14;
                ctx.beginPath();
                ctx.arc(centerX, centerY, ringRad, 0, Math.PI * 2);
                ctx.strokeStyle = `rgba(220, 60, 30, ${0.5 - i * 0.1})`;
                ctx.lineWidth = 2.2 - i * 0.4;
                ctx.stroke();
            }
            // 外圈符文: 环形虚线 & 火焰纹
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius - 8, 0, Math.PI * 2);
            ctx.strokeStyle = '#ff4444';
            ctx.setLineDash([6, 12]);
            ctx.lineWidth = 1.8;
            ctx.stroke();
            ctx.setLineDash([]); // 恢复实线
            
            // 咒印外圈小三角阵列
            const outerRunes = 24;
            for (let i = 0; i < outerRunes; i++) {
                const angle = (i / outerRunes) * Math.PI * 2 + globalRotation * 0.3;
                const x = centerX + Math.cos(angle) * (radius - 10);
                const y = centerY + Math.sin(angle) * (radius - 10);
                ctx.beginPath();
                ctx.moveTo(x + Math.cos(angle + 1.2) * 5, y + Math.sin(angle + 1.2) * 5);
                ctx.lineTo(x + Math.cos(angle - 1.2) * 5, y + Math.sin(angle - 1.2) * 5);
                ctx.lineTo(x + Math.cos(angle) * 10, y + Math.sin(angle) * 10);
                ctx.fillStyle = `rgba(180, 30, 20, 0.7)`;
                ctx.fill();
            }
        }
        
        // 3. 绘制万花筒核心刀刃 (六刃绝阵) —— 炫酷的万花筒纹样
        function drawBlades(rotationOffset) {
            const bladeCount = 6;       // 六刃象征六道之力
            const baseRadius = radius * 0.58; // 刃基部半径约160px
            const tipRadius = radius * 0.92;  // 刃尖伸展半径 250px左右
            
            for (let i = 0; i < bladeCount; i++) {
                const angleStep = (Math.PI * 2 / bladeCount);
                let bladeAngle = i * angleStep + rotationOffset;
                
                ctx.save();
                ctx.translate(centerX, centerY);
                ctx.rotate(bladeAngle);
                ctx.beginPath();
                
                // 动态曲线构造邪魅刀刃 (手里剑风 + 万花筒扭曲感)
                // 采用贝塞尔曲线塑造锋利且带有勾玉弧度的刃
                const r1 = baseRadius + 6 * Math.sin(Date.now() * 0.003 + i); // 微小颤动
                const r2 = tipRadius - 8;
                // 控制点偏移制造弯刀效果
                const cp1x = r1 + 38;
                const cp1y = -12;
                const cp2x = r2 - 20;
                const cp2y = -24;
                const endX = r2;
                const endY = 0;
                
                // 上边缘曲线
                ctx.moveTo(r1, 0);
                ctx.quadraticCurveTo(cp1x, cp1y, cp2x, cp2y);
                ctx.lineTo(endX, endY);
                // 下边缘曲线 (对称, 更诡异)
                ctx.quadraticCurveTo(r2 - 18, 22, r1 + 8, 0);
                ctx.closePath();
                
                // 填充暗黑血色 + 立体感
                const gradBlade = ctx.createLinearGradient(r1, -8, r2, 0);
                gradBlade.addColorStop(0, '#1a0000');
                gradBlade.addColorStop(0.7, '#2a0505');
                gradBlade.addColorStop(1, '#4a0808');
                ctx.fillStyle = gradBlade;
                ctx.fill();
                ctx.shadowBlur = 8;
                ctx.shadowColor = '#ff3300';
                ctx.strokeStyle = '#b33b2a';
                ctx.lineWidth = 1.6;
                ctx.stroke();
                
                // 刃纹咒印: 每个刀刃上增加小型勾玉状点缀
                ctx.beginPath();
                ctx.ellipse(r2 - 26, -6, 7, 9, 0.3, 0, Math.PI * 2);
                ctx.fillStyle = '#aa2222';
                ctx.fill();
                ctx.beginPath();
                ctx.ellipse(r2 - 26, 6, 5, 7, -0.2, 0, Math.PI * 2);
                ctx.fillStyle = '#dd4444';
                ctx.fill();
                
                ctx.restore();
            }
        }
        
        // 4. 绘制内圈六芒星/六角封印阵 (万花筒特有几何)
        function drawInnerHexagram(rotation) {
            const starRadius = radius * 0.42;  // 内六芒星半径
            const points = [];
            // 生成12个点 (两个三角形交错)
            for (let i = 0; i < 6; i++) {
                const angle1 = i * Math.PI * 2 / 6 + rotation;
                const x1 = centerX + Math.cos(angle1) * starRadius;
                const y1 = centerY + Math.sin(angle1) * starRadius;
                points.push({x: x1, y: y1});
                
                const angle2 = (i + 0.5) * Math.PI * 2 / 6 + rotation;
                const x2 = centerX + Math.cos(angle2) * (starRadius * 0.62);
                const y2 = centerY + Math.sin(angle2) * (starRadius * 0.62);
                points.push({x: x2, y: y2});
            }
            ctx.save();
            ctx.shadowBlur = 3;
            ctx.shadowColor = '#ff6347';
            ctx.beginPath();
            for (let i = 0; i < points.length; i++) {
                if (i === 0) ctx.moveTo(points[i].x, points[i].y);
                else ctx.lineTo(points[i].x, points[i].y);
            }
            ctx.closePath();
            ctx.fillStyle = 'rgba(70, 10, 10, 0.75)';
            ctx.fill();
            ctx.strokeStyle = '#ff3a1a';
            ctx.lineWidth = 1.6;
            ctx.stroke();
            
            // 添加内圈悬浮咒文圆点
            for (let i = 0; i < 12; i++) {
                const rad = (i / 12) * Math.PI * 2 + rotation * 1.3;
                const rDot = starRadius * 0.75;
                const xd = centerX + Math.cos(rad) * rDot;
                const yd = centerY + Math.sin(rad) * rDot;
                ctx.beginPath();
                ctx.arc(xd, yd, 2.8 + Math.sin(Date.now() * 0.006 + i) * 1.2, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(255, 80, 40, 0.9)`;
                ctx.fill();
            }
            ctx.restore();
        }
        
        // 5. 绘制三枚强化勾玉 (融入万花筒的古老瞳力)
        function drawTomoe(rotation) {
            const tomoeRadius = radius * 0.33;
            const count = 3;
            const baseAngle = rotation;
            for (let i = 0; i < count; i++) {
                const angle = baseAngle + (i * Math.PI * 2 / count);
                const x = centerX + Math.cos(angle) * tomoeRadius;
                const y = centerY + Math.sin(angle) * tomoeRadius;
                ctx.save();
                ctx.translate(x, y);
                ctx.rotate(angle + Math.PI / 2);
                ctx.beginPath();
                // 绘制经典写轮眼勾玉形态 (弯曲尾)
                ctx.ellipse(0, 0, 13, 19, 0, 0, Math.PI * 2);
                ctx.fillStyle = '#1f0000';
                ctx.fill();
                ctx.beginPath();
                ctx.ellipse(3, -5, 5, 8, 0.5, 0, Math.PI * 2);
                ctx.fillStyle = '#440000';
                ctx.fill();
                // 高光
                ctx.beginPath();
                ctx.arc(-3, -4, 2, 0, Math.PI * 2);
                ctx.fillStyle = '#aa4422';
                ctx.fill();
                // 勾玉尾穗
                ctx.beginPath();
                ctx.moveTo(9, 0);
                ctx.quadraticCurveTo(15, -7, 8, -14);
                ctx.lineTo(3, -6);
                ctx.fillStyle = '#5a1010';
                ctx.fill();
                ctx.restore();
            }
        }
        
        // 6. 绘制中心瞳孔 (具有万花筒独特漩涡纹 & 脉动效果)
        function drawPupil(pulse) {
            // 瞳孔大小随脉动变化 (呼吸感)
            const basePupil = radius * 0.12;
            const pupilR = basePupil + (basePupil * 0.2 * pulse);
            ctx.save();
            ctx.shadowBlur = 12;
            ctx.shadowColor = '#ff0000';
            // 中心黑洞
            ctx.beginPath();
            ctx.arc(centerX, centerY, pupilR * 1.1, 0, Math.PI * 2);
            ctx.fillStyle = '#020000';
            ctx.fill();
            // 瞳孔内万花筒螺旋纹
            ctx.beginPath();
            ctx.arc(centerX, centerY, pupilR * 0.7, 0, Math.PI * 2);
            ctx.fillStyle = '#300000';
            ctx.fill();
            // 瞳孔放射线
            for (let r = 0; r < 8; r++) {
                const radAngle = (r / 8) * Math.PI * 2 + globalRotation * 1.5;
                const x1 = centerX + Math.cos(radAngle) * 5;
                const y1 = centerY + Math.sin(radAngle) * 5;
                const x2 = centerX + Math.cos(radAngle) * (pupilR * 1.4);
                const y2 = centerY + Math.sin(radAngle) * (pupilR * 1.4);
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.strokeStyle = `rgba(255, 80, 40, ${0.5 + pulse * 0.3})`;
                ctx.lineWidth = 2;
                ctx.stroke();
            }
            // 高光血瞳亮点
            ctx.beginPath();
            ctx.arc(centerX - pupilR * 0.3, centerY - pupilR * 0.25, pupilR * 0.23, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(255, 100, 70, 0.9)`;
            ctx.fill();
            ctx.beginPath();
            ctx.arc(centerX + pupilR * 0.2, centerY + pupilR * 0.15, pupilR * 0.12, 0, Math.PI * 2);
            ctx.fillStyle = '#ffaa88';
            ctx.fill();
            ctx.restore();
        }
        
        // 7. 浮动粒子和红炎效果 (动态灵压)
        function drawParticleFlares(time) {
            ctx.save();
            ctx.globalCompositeOperation = 'lighter';
            for (let i = 0; i < 36; i++) {
                const angle = (i * 37.2 + time * 0.8) % (Math.PI * 2);
                const rad = radius * (0.6 + Math.sin(time * 0.002 + i) * 0.12);
                const x = centerX + Math.cos(angle) * rad;
                const y = centerY + Math.sin(angle) * rad;
                const size = 2.2 + Math.sin(time * 0.01 + i) * 1.2;
                ctx.beginPath();
                ctx.arc(x, y, size, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(255, 70, 30, ${0.3 + Math.sin(time * 0.005 + i) * 0.2})`;
                ctx.fill();
                // 血焰拖尾
                ctx.beginPath();
                ctx.arc(x - Math.cos(angle) * 6, y - Math.sin(angle) * 6, size * 0.7, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(255, 40, 0, 0.5)`;
                ctx.fill();
            }
            // 额外旋转咒印光点
            for (let i = 0; i < 12; i++) {
                const ang = (i / 12) * Math.PI * 2 + time * 0.004;
                const ringRad = radius * 0.85;
                const x = centerX + Math.cos(ang) * ringRad;
                const y = centerY + Math.sin(ang) * ringRad;
                ctx.beginPath();
                ctx.arc(x, y, 2.5, 0, Math.PI * 2);
                ctx.fillStyle = `#ff5a2a`;
                ctx.fill();
            }
            ctx.restore();
        }
        
        // 8. 炫光六连星阵 (附加万花筒境界线)
        function drawExtraMangekyoPattern(rotation) {
            ctx.save();
            ctx.shadowBlur = 5;
            ctx.shadowColor = '#ff4422';
            const arms = 6;
            for (let i = 0; i < arms; i++) {
                const ang = (i / arms) * Math.PI * 2 + rotation;
                const x1 = centerX + Math.cos(ang) * (radius * 0.52);
                const y1 = centerY + Math.sin(ang) * (radius * 0.52);
                const x2 = centerX + Math.cos(ang + 0.25) * (radius * 0.75);
                const y2 = centerY + Math.sin(ang + 0.25) * (radius * 0.75);
                const x3 = centerX + Math.cos(ang - 0.25) * (radius * 0.75);
                const y3 = centerY + Math.sin(ang - 0.25) * (radius * 0.75);
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.lineTo(x3, y3);
                ctx.fillStyle = `rgba(100, 20, 15, 0.5)`;
                ctx.fill();
                ctx.strokeStyle = '#ee4422';
                ctx.lineWidth = 1.2;
                ctx.stroke();
            }
            // 结印文字效果
            ctx.font = `bold ${Math.floor(radius * 0.07)}px "KaiTi", "Noto Sans CJK JP"`;
            ctx.fillStyle = `rgba(220, 70, 40, 0.55)`;
            ctx.shadowBlur = 2;
            ctx.fillText("卍", centerX - 12, centerY - radius * 0.25);
            ctx.fillText("解", centerX + 10, centerY + radius * 0.28);
            ctx.restore();
        }
        
        // 主渲染循环 (动态整合)
        function drawFrame(now) {
            if (!startTime) startTime = now;
            const elapsed = now - startTime;
            
            // 脉动值 (sin波形 周期大约2.3秒)
            pulseFactor = (Math.sin(elapsed * 0.0027) + 1) / 2;   // 0-1之间
            
            // 清空画布
            ctx.clearRect(0, 0, SIZE, SIZE);
            
            // 1. 邪瞳背景
            drawBackground();
            
            // 2. 外层结界
            drawOuterRings();
            
            // 3. 核心六刃 (万花筒主要纹章)
            drawBlades(globalRotation);
            
            // 4. 六芒星内封印阵 (多旋转层叠加)
            drawInnerHexagram(globalRotation * 0.9);
            
            // 5. 三勾玉瞳力之源 (经典传承)
            drawTomoe(globalRotation * 0.6);
            
            // 6. 复杂万花筒纹路(额外境界)
            drawExtraMangekyoPattern(globalRotation * 1.2);
            
            // 7. 中心瞳孔带脉动
            drawPupil(pulseFactor);
            
            // 8. 动态粒子炎灵效果
            drawParticleFlares(elapsed);
            
            // 最后增加一层高光叠加，腥红薄膜 (赋予深度)
            ctx.save();
            ctx.globalCompositeOperation = 'overlay';
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius * 0.45, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(180, 30, 10, ${0.08 + Math.sin(elapsed * 0.003) * 0.04})`;
            ctx.fill();
            ctx.restore();
            
            // 加一圈外发光描边，增强立体感
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius + 5, 0, Math.PI * 2);
            ctx.strokeStyle = `rgba(255, 80, 40, 0.25)`;
            ctx.lineWidth = 3;
            ctx.stroke();
        }
        
        // 动画循环（旋转用 speed * dt 累加，便于悬停改 speed 时不跳角）
        let lastAnimTime = null;
        function animate(timestamp) {
            const dt =
                lastAnimTime == null ? 0 : Math.min(80, Math.max(0, timestamp - lastAnimTime));
            lastAnimTime = timestamp;
            globalRotation += speed * dt;
            drawFrame(timestamp);
            animationId = requestAnimationFrame(animate);
        }
        
        // 适配窗口尺寸和高清显示(无需拉伸已固定600px，但为了CSS确保圆滑)
        function handleResize() {
            // 保持canvas CSS尺寸自适应，但是画质不会失真; 由于已固定宽高600px，无需额外处理。
            // 只是为了保持中心坐标重新计算 (但中心固定不变)
            centerX = SIZE / 2;
            centerY = SIZE / 2;
            radius = SIZE * 0.46;
        }
        
        window.addEventListener('resize', () => {
            handleResize();
        });
        
        // 启动动画（始终 requestAnimationFrame；减少动态效果时仅已在上方降低 speed）
        startTime = null;
        animationId = requestAnimationFrame(animate);
        
        // 清理动画 (页面关闭时)
        window.addEventListener('beforeunload', () => {
            if (animationId) {
                cancelAnimationFrame(animationId);
            }
        });
        
        handleResize();
    })();