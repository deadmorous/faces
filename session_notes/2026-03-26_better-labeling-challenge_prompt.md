# Better labeling challenge

❯ We already have great Web UI in the faces app, and the main thing to do now seems to be an enhancement of face labeling process. For batch
labeling, we have
- similar faces view;
- classify view;
- multiselect on photo view (mostly for marking as non-face/foreign).

Every of these views provides unique capabilities and is quite useful in grouping faces and assigning a label to the group; but all of them are not
ideal, due to limitations in both design and how we assess similarity. Let me focus on a few things that we could improve here and then we can
brainstorm further steps and create a plan.

1. From my experience, similar faces work well when there are many unlabeled unprocessed faces, after a new scan. Later on, as unlabeled set gets
"depleted", more and more other persons' faces squeeze in, and finally the view shows a mess of different faces. This is not very useful because it's
 difficult to find and clich the right faces. Threshold adjustment does not help much here, as faces are already sorted by distance to the seed face.
2. Similar effect is noticed in the classify view. Faces are classified incorrectly, but reference time range can improve this a bit.
3. Multiselecting foreign faces and non-faces in the photo view work great and is quite useful when we have a photo showing a croud. However, when we
 have multiple photos of the same croud, we have to repeat the same thing for every photo.
4. Many foreign faces "contaminate" the set of faces, yet those could potentially be detected and filtered out: I mean cases when there is a
big-sized face (or a few faces) in the foreground, and very small faces in the background. It would be great to have a mechanism to ignore such
"background faces" when they are not labeled, perhaps with a threshold.

As of point 1, I think that one of the "cheapest" way to improve labeling experience is to have a "follow mode", such that similar faces are picked
only from a specific time range relative to the seed face (same day, plus/minus 1 day, 2 days, week, month; unconstrained). This is the only thing we
 can do easily, among other things expressing the idea of taking into account more things than just face embeddings (could also be clothes or
something else).

I invite you to give more feedback on the above topic, so that we can come to certain things to improve labeling and then implement these.
