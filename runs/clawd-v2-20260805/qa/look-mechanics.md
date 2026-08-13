# Clawd Look Mechanics

## Identity Lock

Clawd is the existing strict pixel-art mascot: a compact orange square body, four short orange legs, dark blue side ear/clip pieces, a cream stepped top outline, and small dark square eyes. Preserve the legacy palette, hard block edges, body proportions, and grounded baseline.

## Natural Looking Motion

Clawd's lower body and four feet remain the stable anchor. Looking is expressed by a restrained turn of the upper face/head plane, with the two dark square eyes shifting together toward the target direction. The cream top outline and blue side pieces follow the upper face with small stepped occlusion changes; they do not independently float or rotate. The orange body keeps its volume and does not rock as a whole.

The eyes remain square pixel features, never round replacement eyes. For vertical directions, the eyes move within the face and the top outline compresses or opens by a few stepped pixels. For horizontal directions, the upper face shifts and one blue side piece becomes slightly more or less visible while the feet, lower body, and baseline stay registered. Diagonals interpolate these changes evenly.

## Cardinal Pose Families

- `000` up: eyes and upper face read toward the top edge; the cream top contour is slightly more prominent and the lower face remains anchored.
- `090` screen-right: upper face and eye pair shift visibly toward screen-right; the screen-right side reads more open while the opposite blue side piece is a little more occluded.
- `180` down: eyes and upper face read toward the bottom edge; the top contour is slightly less prominent and the lower face becomes the visual lead.
- `270` screen-left: mirror the horizontal meaning of `090` in viewer coordinates; the upper face and eye pair visibly shift toward screen-left, with opposing side-piece occlusion.

## Motion Budget

Each 22.5-degree step changes the eye pair and upper-face registration by a similar small pixel amount. Keep the lower body, feet, silhouette scale, and baseline stable. Do not use whole-sprite rotation, skew, affine tilt, new props, shadows, glows, labels, arrows, or detached effects. The row-9 boundary `157.5 -> 180` and row-10 boundary `337.5 -> 000` must be one-step continuations of the same arc.

