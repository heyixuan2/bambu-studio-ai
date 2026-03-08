# Colorize 几何增强方案 — 眼睛等小特征保护

## 问题分析

眼睛、按钮等小特征容易丢失的原因：

| 层级 | 原因 |
|------|------|
| **贴图** | 像素占比 < min_pct，未被选为独立颜色；或 < island_size 被 cleanup 合并 |
| **贴图** | preserve_salient_regions 依赖「区域 vs 邻域对比度」，眼睛若与肤色接近会漏掉 |
| **3D** | 顶点色采样是均匀的，眼睛区域若 UV 拉伸或细分不足，分辨率不够 |
| **本质** | 当前逻辑纯靠贴图像素，没有利用 3D 几何信息（眼睛通常是凸起） |

## 可行方案

### 方案 A：Blender 烘焙曲率图（推荐）

**思路**：眼睛、鼻子、按钮等是**凸面**（高曲率）。在 Blender 中烘焙曲率到纹理，与贴图同 UV，得到一张「几何显著图」。

**流程**：
1. 导入 GLB → 用 Geometry Nodes 的 Pointiness/Curvature 输出到顶点色
2. Bake 到 UV 纹理（与 base color 同分辨率）
3. 在 colorize 中：`protected_mask |= (curvature_map > threshold)`，与现有 preserve_salient_regions 合并
4. 高曲率区域不参与 island cleanup 和 smoothing

**优点**：利用 Blender 内置能力，不依赖 trimesh；曲率与 UV 一一对应  
**缺点**：多一次 Blender 调用（可与 texture 提取合并）

---

### 方案 B：Trimesh 顶点曲率 → UV 栅格化

**思路**：用 trimesh 的 `vertex_defects`（凸=正、凹=负）计算每顶点曲率，再按 UV 栅格化到纹理空间。

**流程**：
1. 用 pygltflib 解析 GLB：顶点、面、TEXCOORD_0
2. 用 trimesh 构建 mesh，计算 `vertex_defects`
3. 对每个面：3 个顶点的 UV 构成三角形，栅格化到纹理，像素值 = max(3 顶点曲率)
4. 得到 curvature_map，与方案 A 同样并入 protected_mask

**优点**：纯 Python，无需额外 Blender  
**缺点**：UV 栅格化要自己实现；需处理多材质/多 mesh

---

### 方案 C：自适应细分（Blender 内）

**思路**：在 `apply_vertex_colors` 的 Blender 脚本中，对高曲率区域做更多细分。

**实现**：
- 用 Geometry Nodes 或 Python 计算每面曲率
- 对曲率 > 阈值的面做 `subdivide`，其余保持
- 或：整体多一次 subdivision，但只在高曲率区域

**优点**：改动集中在 Blender 脚本  
**缺点**：面数增加，导出变慢；需要判断「高曲率」的阈值

---

### 方案 D：顶点色后处理（OBJ 导出后）

**思路**：导出 OBJ 后，对高曲率顶点重新采样**原始贴图**（非量化版），再 snap 到 8 色。

**流程**：
1. 导出时保留 UV（`export_uv=True`）
2. 用 trimesh 加载 OBJ，计算 vertex_defects
3. 高曲率顶点：用其 UV 从**原始纹理**采样，找最近 8 色之一
4. 写回 OBJ 的顶点色

**优点**：不改变主流程，作为后处理  
**缺点**：需要保留并传入原始纹理；OBJ 需带 UV

---

## 已实现：方案 B（Trimesh + UV 栅格化）

在 colorize v4 中已实现 `--geometry-protect`（默认开启）：

- 使用 trimesh `vertex_defects` 计算每顶点曲率（凸=正）
- 将高曲率面栅格化到纹理空间，与 `preserve_salient_regions` 合并
- 高曲率区域（眼睛、按钮等）不参与 island cleanup 和 smoothing
- 用 `--no-geometry-protect` 可关闭

**依赖**：trimesh（已有）、pygltflib（已有）。可选：scikit-image 用于更快三角栅格化。

## 其他方案（未实现）

1. **方案 A**：Blender 烘焙曲率图 — 可与方案 B 叠加
2. **方案 D**：顶点色后处理 — 作为可选后处理

## 参数建议

- 曲率阈值：`vertex_defects > 0.1` 或取 top 5% 凸顶点
- `preserve_salient_regions` 的 `min_region`：可降到 32，以保留更小眼睛
- `contrast_delta`：可降到 12，让更多小区域被视为「高对比」
