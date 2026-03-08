Epic Fantasy SDXL Generation Analysis
1. Model Ranking (SDXL Models by Category)

Below is a comparison of the user’s SDXL models, rated 1–10 in each key category. Higher scores indicate stronger performance for that type of generation:

Model	Realistic Images	Photorealistic People	Fantasy Scenes	Fantasy Monsters	Fantasy Characters	Beautiful People	Battle Scenes
Juggernaut XL (v13 Ragnarok)	9 – Excels at ultra-realism
openlaboratory.ai
openlaboratory.ai
	10 – Top-tier for lifelike humans
openlaboratory.ai
openlaboratory.ai
	8 – Great cinematic detail, but leans photoreal	7 – Can depict creatures, but not specialized	9 – High-quality heroic characters (realistic style)	9 – Produces very attractive, lifelike faces
openlaboratory.ai
	8 – Cinematic and coherent, minor struggles with large crowds
Realism Engine SDXL (v3)	9 – Very true-to-life outputs
openlaboratory.ai
openlaboratory.ai
	9 – Handles diverse faces/lighting with ease
openlaboratory.ai
openlaboratory.ai
	7 – Primarily tuned for realism, less “magic” flair	6 – Not trained for fantasy creatures (will render realistically)	8 – Excellent anatomy/skin, but creative styles need boosts	9 – Extremely detailed skin/hair; great for portrait beauty	7 – Good realism, may need art LoRAs for epic feel
RealVis XL (V5)	8 – Clean and photoreal (slightly less forgiving than above)	9 – Nearly undetectable AI faces; superb skin/hair detail
medium.com
	8 – Can do lifelike fantasy settings (needs strong prompts)	7 – Handles “real” monsters (e.g. realistic dragons) well
medium.com
	8 – Strong at realistic elves/knights (human-centric strength)	8 – Produces natural, proportional figures
medium.com
	8 – Photographic style; epic scenes need stylistic help
CyberRealistic XL (v5.7)	9 – “Ultra-clean” photoreal generations
diffus.me
	9 – Polished, high-fidelity people (male rendering improved)
diffus.me
diffus.me
	7 – Focuses on reality; fantasy scenes look realistic (less surreal)	7 – Renders monsters in realistic style (may lack fantastical flair)	8 – Great for grounded fantasy characters (e.g. gritty realism)	9 – Excellent for glossy, magazine-quality portraits	7 – Detailed and clean, but use art LoRAs for drama
DreamShaper XL (Turbo)	7 – Good mix of real and art, but not as photoreal as above	8 – Can produce realistic people, with slight artistic touch
shakersai.com
	10 – Outstanding for fantasy landscapes and atmospheres
shakersai.com
	9 – Excels at mythical creatures with imaginative styling
shakersai.com
	10 – Versatile: epic heroes or storybook characters
shakersai.com
	8 – Makes beautiful subjects with a painterly charm	9 – Dramatic lighting and color for battles, very storytelling-oriented
shakersai.com
shakersai.com

Notes: Juggernaut XL is a flagship SDXL merge known for photorealism and coherent compositions
openlaboratory.ai
openlaboratory.ai
. It handles faces and anatomy exceptionally (it was fine-tuned with improved captions for hands/faces)
openlaboratory.ai
. Realism Engine SDXL also delivers top-tier realism with an integrated VAE for color accuracy
openlaboratory.ai
openlaboratory.ai
, making it excellent for portraits and everyday scenes. RealVis XL and CyberRealistic XL are similarly strong in realistic human detail – RealVis is noted for human renders so convincing they “can’t be recognized as AI”
medium.com
, and CyberRealistic is a go-to for ultra-clean, polished photoreal outputs
diffus.me
. These tend to depict fantasy themes in a realistic style (e.g. a dragon as if photographed). In contrast, DreamShaper XL strikes a perfect balance between realism and artistic fantasy. It can make a scene feel immersive and imaginative while still maintaining believable detail
shakersai.com
. This makes DreamShaper ideal for high-fantasy art – it handles epic landscapes, mythical creatures, and heroic characters with dramatic lighting and rich color
shakersai.com
shakersai.com
. Its versatility in style means it can do painterly or cinematic looks on demand, which is great for battles or storybook illustrations. Overall, using a more photoreal model (Juggernaut, Realism Engine, RealVis, CyberRealistic) will give truer-to-life results (great for “game character portrait” style), while a hybrid/art model like DreamShaper XL will better capture the magic and epic scale of fantasy scenes.

2. VAE Matching for Each Category

Using an appropriate VAE (Variational Autoencoder) is crucial for color and contrast in SDXL. Many finetuned SDXL models come with a baked-in VAE:

Juggernaut XL: Includes a built-in VAE, so no external VAE is needed
openlaboratory.ai
. Its baked VAE is already optimized for photoreal output. For realistic images/people, simply use Juggernaut as-is. If you attach the external SDXL VAE on top, it can sometimes oversaturate – not necessary here.

Realism Engine SDXL: Integrated VAE from version 2.0 onward
openlaboratory.ai
. This model was distributed with a baked VAE for convenience, ensuring accurate colors out-of-the-box. Use its internal VAE for all categories (especially portraits where skin tone fidelity is important). No need for an external VAE.

RealVis XL / CyberRealistic XL: These models also have baked-in VAEs (CyberRealistic explicitly notes “VAE is already baked in”
diffus.me
). For photorealistic people and realistic scenes, the baked VAE yields optimal results (neutral color balance, reduced artifacts). If using SDXL base or any model without a VAE, you should load the SDXL Official VAE
huggingface.co
. The official SDXL VAE (published Feb 2024) is the go-to for models that require an external VAE
reddit.com
 – it improves dynamic range and fixes washed-out colors.

Fantasy-focused models (e.g. DreamShaper XL): DreamShaper XL releases often provide both “baked VAE” and “no VAE” variants
openlaboratory.ai
. It’s recommended to use the baked-VAE version if available (to get the colors the creator intended). If your DreamShaper checkpoint lacks a VAE, again use the standard SDXL VAE file. For fantasy scenes/monsters, a good VAE will preserve rich colors (e.g. fiery spell effects, sunsets) without clipping. The SDXL VAE is generally well-balanced for both realism and vibrant fantasy art.

High Fantasy Characters/Battle scenes: If using a very realism-oriented model (which might slightly mute fantastical colors), consider an alternate VAE like “SDXL Unclip VAE” or others if recommended by the model author. In most cases, though, the SDXL VAE (official) works universally well across photoreal and fantasy outputs. For example, StableYogi’s models explicitly require the SDXL VAE for best results
huggingface.co
 – this VAE tends to boost saturation and contrast, which can help fantasy images “pop” while still looking natural.

VAE Summary: Use the model’s baked VAE whenever provided (Juggernaut, Realism Engine, CyberRealistic, etc.), as it is tuned for that model’s output. If the model has no internal VAE (common in early SDXL finetunes or certain LoRA merges), load the “SDXL 1.0 VAE” (the StabilityAI SDXL VAE) in Automatic1111. This is recommended for all categories – it yields good color accuracy for realism and can enhance dynamic range for fantasy scenes. Always avoid stacking two VAEs (ensure you don’t accidentally apply an external VAE on a model that already has one). In short: photoreal categories rely on baked VAEs for true-to-life tones, while fantasy categories benefit from the SDXL VAE’s ability to handle vivid colors and darks without banding.

3. LoRA Matching per Category

The user’s LoRA library contains several versatile SDXL LoRAs. To maximize results in each category, here are the best LoRAs (and strengths) to use, along with any trigger keywords and ideal model pairings:

Realistic Images (General): You’ll want to add detail without deviating from realism. Use Add-Detail-XL LoRA (at ~0.6–0.7 weight) to enhance small details and overall sharpness – this LoRA works well on photos and doesn’t cartoonize the image
wiki.monai.art
. Pair it with Juggernaut or Realism Engine for ultra-crisp results. Avoid strong “style” LoRAs here; focus on detailers. If the image contains a face, the DetailedEyes V3 LoRA at around 0.5–0.8 is helpful for eye clarity (it will sharpen the irises and lashes). It’s subtle, so it won’t ruin realism at moderate strength. Keywords: DetailedEyes doesn’t usually need a trigger word (it affects any eyes in frame). CinematicStyle v1 can be applied lightly (~0.3–0.5) if you want a slight cinematic contrast/lighting without looking “filtered.” This LoRA, when paired with a photoreal model, gives a nice depth and professional photo look.

Photorealistic People: For portraits or full-body shots of people, the goal is beauty + realism. DetailedEyes V3 is highly recommended at 0.7–0.8 weight to ensure sharp, expressive eyes (critical for portraits). You might also use Babes by StableYogi (Pony) XL V4 LoRA at ~1.0 for female subjects – this LoRA was trained to enhance body and facial aesthetics (especially for women) while maintaining realistic anatomy (it’s literally described as “enhanced body anatomy, hands, colors, and detail tweaks” by the author). It has no special trigger word; it affects the overall style (you’ll get more polished, magazine-like beautiful people). Pair BabesV4 with Juggernaut XL or CyberRealistic XL – those models’ realism plus the LoRA’s glamour yields stunning photorealistic portraits. For male subjects, BabesV4 is less applicable (it skews feminine features), so instead consider using just detailers (DetailedEyes, Add-Detail) and perhaps DreamyStyle XL at low weight (0.3–0.5) if you want a slight dreamy glow. CinematicStyle v1 is also great here (0.5–0.6) to give that cinematic portrait lighting – for example, a rim light or soft filmic shadows, which enhances “beautiful people” shots. Best model pairing: Juggernaut XL or Realism Engine (for ultimate face fidelity) with these LoRAs. These models already do well with diverse faces, and LoRAs fill any gaps in stylization.

Fantasy Scenes: For wide shots of landscapes, group scenes, or magical environments, leverage CinematicStyle v1 at 0.5–0.7. This will infuse the scene with dramatic lighting, contrast, and a movie-like atmosphere (think high-budget fantasy film look). Combine it with DreamyStyle XL LoRA (≈ 0.6–0.8 strength) to introduce a soft, otherworldly touch – DreamyStyle will make colors more ethereal and add a slight “fantastical” art vibe (very useful for enchanted forests, glowing ruins, etc.). If your scene includes a lot of fine detail (ancient runes, elaborate architecture), bring in Add-Detail-XL at ~0.5. Even though this LoRA was designed with anime/painted styles in mind, at moderate weight it will still enhance texture detail in any style
wiki.monai.art
. Keywords: These scene style LoRAs typically don’t need explicit triggers (they affect overall tone), but you can prompt things like “cinematic lighting, epic scale” to synergize with CinematicStyle. Model pairing: DreamShaper XL is fantastic with these LoRAs (it already excels at fantasy scenes
shakersai.com
, and the LoRAs push it further). You can also use Juggernaut or RealVis if you want a more realistic base – the LoRAs will help inject the missing fantasy atmosphere.

Fantasy Monsters: The user’s current LoRAs are general and not specific to creatures, but they can still help. CinematicStyle v1 (0.5–0.6) is great for making a monster scene feel epic or ominous – e.g. dramatic shadows on a dragon or a burst of light behind a summoned demon. DreamyStyle XL at ~0.4–0.6 can add a surreal, mythic quality (useful if you want the monster to have a slightly illustrated or “legendary” feel instead of looking like a National Geographic animal). Add-Detail-XL (0.6) is useful here to ensure scales, fur, or mystical effects on the creature are rendered in high detail. If the monster has eyes visible, DetailedEyes could even sharpen them (though monstrous eyes might not need human-level detail). Note: This is one category where a specialized LoRA might be missing – e.g., a dragon-specific LoRA or “fantasy creature” LoRA could boost authenticity (see Missing Assets below for suggestions). For now, pairing CinematicStyle and DreamyStyle with a versatile model like DreamShaper XL or a photoreal model (to get realistic anatomy) can yield great results. For example, RealVis XL plus these LoRAs can produce a photoreal dragon with atmospheric lighting (RealVis ensures the scales/skin look real, LoRAs give the magic glow and drama).

Fantasy Characters (Heroic figures in armor, mages, etc.): This overlaps between people and scene style. CinematicStyle v1 (0.5–0.7) is almost a must-have – it will make your character look like they’re in a still from a movie (ideal for a knight on castle ramparts at golden hour, for instance). Add-Detail-XL (0.6–0.8) is very useful on armored characters or intricate costumes – it will sharpen engravings on armor, fabric textures, weapon details, etc. Use DetailedEyes V3 (0.7) if the character’s face is visible and important; you want those eyes to be alive (especially for close-ups). For female characters or any character where you want an attractive face/body, apply Babes XL V4 LoRA at around 0.8–1.0. This LoRA will ensure the character has idealized features (flawless skin, balanced facial structure, etc.) while preserving the fantasy attire (it was trained on a variety of styles, so it shouldn’t conflict with armor or clothing prompts). Combine BabesV4 with a strong base model like Juggernaut or CyberRealistic for very realistic-looking characters, or with DreamShaper for slightly more artsy characters. Keywords: If Babes LoRA came with any trigger (the author StableYogi sometimes provides an “embedding” or tag, but in this case it’s applied globally), just describing the character normally is fine. You might include adjectives like “gorgeous, athletic” if appropriate – Babes will amplify those traits. For armor/clothing, prompt those explicitly (LoRAs will then enhance them). We’ve found Juggernaut XL + Add-Detail + CinematicStyle is a killer combo for armored characters – Juggernaut gives realistic metals and anatomy, Add-Detail sharpens filigree, CinematicStyle adds epic lighting (e.g. glints on the armor, volumetric rays in environment).

“Beautiful People” (glamour shots, pin-ups, influencers): Here the Babes by StableYogi LoRA is the star. Use it at 1.0 weight for maximum effect – it was literally designed to produce gorgeous, well-proportioned people with excellent skin and colors
huggingface.co
huggingface.co
. It pairs excellently with CyberRealistic XL or Realism Engine for truly photoreal glam shots. In your positive prompt, you can use keywords like “perfect face, flawless skin, beautiful”, etc., and BabesV4 will reinforce those (it doesn’t require a special trigger, but it responds to beauty-related descriptors). Along with Babes, use DetailedEyes V3 (0.8) to get those sparkling eyes, and possibly DreamyStyle XL (0.3–0.5) if you want a soft, dreamy lighting (like a diffuser lens effect common in glamour photography). CinematicStyle can also be used (0.4) if you want a sharper, high-contrast studio look instead – it really depends on whether you want a soft romantic feel (use DreamyStyle) or a vivid dramatic feel (use CinematicStyle). For male beauty shots, you can still use these LoRAs, but BabesV4 might slightly feminize features – if that’s a concern, dial it down to 0.5 or use just the other LoRAs. Best model pairing: any photoreal model (Juggernaut, RealVis, CyberRealistic) will do a great job, since these LoRAs will handle the aesthetic enhancement. For example, CyberRealistic XL with BabesV4 has been reported to produce extremely clean and attractive portraits (since CyberRealistic is ultra-clean photoreal and Babes adds the beauty/fashion aspect).

Battle Scenes: Dynamic battle scenes (multiple characters, motion, effects) benefit from LoRAs that enhance atmosphere and detail. CinematicStyle v1 is highly recommended at ~0.6–0.8 – it will give your battle a dramatic, high-shutter-speed look with balanced contrast (almost like a frame from a cinematic trailer). This helps make sense of chaotic action with good lighting. Add-Detail-XL (0.5–0.7) will ensure things like flying debris, armor on multiple fighters, and background elements stay detailed even at medium range. If your battle has faces visible (e.g. a close-up of a hero amid the fight), use DetailedEyes but often battle shots are full-body or groups, so it may not be needed. DreamyStyle XL can be applied lightly (0.3–0.4) if you want a more stylized, painterly battle (for example, a war scene that looks like an art piece with motion blur and softer edges). But if you want gritty realism, you might skip DreamyStyle. BabesV4 generally isn’t used for battles unless your scene specifically focuses on a beautiful warrior – it could slightly distract by beautifying everyone in frame (not always desired in a gritty battle). So, keep Babes off or low if a rough battle is the goal. Ideal model pairing: DreamShaper XL with CinematicStyle is fantastic for battles – DreamShaper already renders dramatic scenes well, and the LoRA pushes it to “movie still” quality. If you prefer a photoreal war photo vibe (like a realistic medieval battle), Juggernaut XL or RealVis XL with Add-Detail and CinematicStyle will give very convincing results (just remember to use a high steps count or high-res fix for multi-character coherence). In battle scenes, where many elements are present, these LoRAs help maintain coherence: CinematicStyle ties the lighting together, Add-Detail prevents muddy textures, making the overall image clearer and more intense.

4. Embedding Matching per Category

The user’s embedding library (textual inversions) includes several powerful positive and negative embeddings. These can significantly influence style and quality. Here are recommended embeddings for each category, with notes on how to use them in prompts:

Realistic/Photorealistic Images: Leverage the StableYogi embeddings for quality boosts. Include <embedding:stable_yogis_pdxl_positives> at the start of your positive prompt. This positive TI was designed to improve overall realism, detail, and “groundedness” of SDXL outputs
huggingface.co
civitai.green
. It works universally (portraits, scenes, etc.) by guiding the model toward a high-quality photographic style. Alongside it, use <embedding:stable_yogis_realism_positives_v1> – this further reinforces photorealism. These two together have been shown to consistently elevate image fidelity (they are recommended by the author for use with many models
civitai.green
). In the negative prompt, utilize the companion negatives: <embedding:stable_yogis_pdxl_negatives2-neg> and <embedding:stable_yogis_anatomy_negatives_v1-neg>. The “PDXL negatives” embedding will fight against common quality issues (blur, low detail, etc.), and the anatomy negative will specifically help prevent warped limbs or faces. You should also include <embedding:negative_hands> in the negative prompt – this is a specialized TI to reduce bad hand rendering. For realistic images of people, bad hands/feet are a notorious problem, and this embedding can strongly mitigate that. All these negative embeddings can be listed in the negative prompt (they don’t conflict – they cover different aspects of “badness”). For example: Negative prompt: blurry, low quality, <embedding:stable_yogis_pdxl_negatives2-neg>, <embedding:stable_yogis_anatomy_negatives_v1-neg>, <embedding:negative_hands>, <embedding:sdxl_cyberrealistic_simpleneg-neg>. Notably, sdxl_cyberrealistic_simpleneg-neg is another excellent negative TI (it comes from the CyberRealistic model). It’s optimized to remove things like CGI/painting artifacts and keep outputs “photo-only”
diffus.me
. It’s a good general negative addition for any photorealistic generation. Use it in any scenario where you want to avoid an illustration look. With these in place, your realistic images will come out sharper and with far fewer flaws (less distortions, no strange text or watermarks, etc.).

High Fantasy Scenes & Characters: When creating very fantastical images, you might dial back the “too realistic” embeddings slightly depending on the desired style. However, the StableYogi positive embeddings (stable_yogis_pdxl_positives and realism_positives_v1) are still beneficial – they act like a quality filter to ensure the model’s highest fidelity. We recommend keeping the positive embeddings even for fantasy (they help with anatomy and overall image coherence). Then use prompt wording to steer style (e.g. add “(illustration:1.2)” or similar if you want a more painted look – the embeddings will not prevent an illustrative style, they just boost quality). For negative embeddings in fantasy: continue to use the anatomy and negative_hands embeddings – even if you’re making an orc or dragon, you likely want correct anatomy for that creature (unless intentionally surreal). The sdxl_cyberrealistic_simpleneg can be used if you want to keep things on the realistic side (it will discourage an overly cartoonish style). If instead you do want a slightly more painterly/dreamy result, you might omit cyberrealistic_simpleneg so that the model isn’t overly biased toward pure photorealism. Another useful embedding in fantasy prompts (if available in your library) is bad_picture_chill or EasyNegative (if an SDXL-trained version exists) – these are generic negative TIs to reduce bad compositions and artifacts. For instance, EasyNegative (originally for SD1.5) has an SDXL adaptation that some users employ to make the image “cleaner” in negatives
comfyui-wiki.com
. If you have it, you can include it (e.g. EasyNegativeXL-neg) along with StableYogi’s. In summary, combine multiple negatives for fantasy as well: hand/anatomy fixes + general quality negatives. This ensures even a complex multi-character battle or a glowing magical scene stays free of unwanted elements.

Portraits of Beautiful People: Use the same positive embeddings (StableYogi PDXL positives) – these help achieve that “masterpiece, best quality” effect that many prompts aim for (they were literally created to boost quality – StableYogi’s positive/negative set is highly regarded
civitai.green
). In negatives, besides the usual (bad hands, etc.), definitely include any face-specific negative embedding if available. For example, the user might have a “bad-face” embedding or the “GLOBAL_BAD” token (in the user’s negative prompt JSON we saw GLOBAL_BAD). It appears GLOBAL_BAD in the user’s setup likely stands for a combination of negative embeddings (possibly a shorthand to insert all the StableYogi negatives). Ensure whatever that placeholder is, it includes things like “bad face, disfigured, ugly” if you are specifically focusing on beauty. In practice, the negative prompt for a beauty portrait might be: bad quality, blurry, <embedding:negative_hands>, <embedding:stable_yogis_anatomy_negatives_v1-neg>, <embedding:stable_yogis_pdxl_negatives2-neg>, <embedding:sdxl_cyberrealistic_simpleneg-neg>, deformed, asymmetrical. This covers technical flaws and aesthetic flaws. On the positive side, you could also experiment with any positive style embeddings you have: e.g., AnalogStyle (if there’s an SDXL version) for a film-like look, or EtherealBeauty (StableYogi provided some 1.5-era embeddings like “EtherealBeauty” – if an XL version exists, it could add a dreamy beauty glow). Check your library for any positively-termed embeddings and see their documentation. If they’re meant for 1.5, they might not work well on SDXL, so prefer those explicitly labeled for SDXL.

Battle Scenes/Complex Scenes: Use the full suite of negative embeddings here. With many elements in a battle, the risk of weird artifacts increases. The StableYogi negatives plus negative_hand will tackle most issues (extra limbs, melted faces of background characters, etc.). It’s also wise to add a few textual negatives for composition issues: e.g. “high contrast halo, double head, duplicate” – some users include a “composition-neg” embedding if they have one. If not, writing those terms is fine. On the positive side, if the battle is meant to be illustrated (like a concept art), you might omit the realism-positive embedding to allow a more raw art style. But if you want a cinematic realistic battle, keep them in. A trick: you can use the positive embeddings but lower their influence by putting them later in the prompt or reducing their weight (e.g. writing (embedding:stable_yogis_pdxl_positives:0.7)). This way you still get some benefit without overriding a stylized prompt. Generally, though, these embeddings are fairly compatible with various styles – they mostly act to improve quality rather than enforce a particular look, so they can be included in most cases for a net gain in output fidelity.

Prompt Stage Guidance: Always put positive embeddings at the very start of the positive prompt (this gives them prominence in Stable Diffusion’s parsing). For negatives, it’s the opposite – list all your negative embeddings and terms in the negative prompt field. The user’s practice of using a placeholder like GLOBAL_BAD to inject a set of negatives is smart for consistency. If possible, continue that: define GLOBAL_BAD to include all your preferred negative embeddings and terms so you don’t forget any. One caveat: using many embeddings can sometimes increase VRAM usage and slow down generation slightly, but on a 24GB system this is not a big issue and the quality trade-off is worth it.

To recap, the must-have embeddings the user already has are StableYogi’s positives (use for all categories)
civitai.green
, StableYogi’s negatives
civitai.green
, the anatomy/hands negatives, and CyberRealistic’s simpleneg. Combined, these cover most quality issues and will yield consistently high-grade images across realism and fantasy.

5. Missing Assets (Recommended Additions)

To further enhance fantasy, realism, and photorealism, the user may consider acquiring a few highly-regarded SDXL assets not currently in their library:

SDXL Models: A few top-tier models could complement the current set:

NightVision XL: A photorealistic SDXL model known for its baked-in VAE and effortless real-life results
medium.com
. It excels at landscapes, architecture, and vehicles, and does very well with human subjects too. If Juggernaut or RealismEngine ever struggle with a certain subject, NightVision XL is a great alternative for pure realism. (Download: Civitai – “NightVision XL”).

LEOSAM’s HelloWorld XL: A highly detailed model that produces stunning realism and depth
shakersai.com
. It’s particularly good with textures and complex scenes (though note it can be VRAM-hungry and sometimes oversmooth textures
shakersai.com
). This would be useful for scenarios where you need extreme detail or a different style of photorealism. (Available on Civitai).

Realism Engine SDXL (latest v3.0): If not already in the library, this model is a must-try for portraits. It was mentioned above and truly shines for faces and skin
openlaboratory.ai
. It has built-in VAE and is pretty straightforward to prompt. Download from Civitai
openlaboratory.ai
 (creator: razzz).

Epic Realism XL / EpiCRealism SDXL: Another community-favorite merge for realism. It balances sharp details with soft focus nicely
shakersai.com
shakersai.com
. Many users cite it for portrait and fashion shots. Would be a nice addition to compare against CyberRealistic/RealVis styles.

Nova Reality XL: A model specialized for cinematic fantasy backgrounds and scenes
shakersai.com
shakersai.com
. It’s built on the Illustrious base and is praised for immersive, hyper-detailed fantasy images (great for “epic battle in ancient ruins” type prompts). This model can produce grand, film-like fantasy visuals that might be hard to get with strictly photoreal models. (On Civitai – creator Crody).

Starlight XL Animated: If you venture into darker fantasy or horror themes, Starlight XL is a finetune known for fantasy horror and moody atmospheres
shakersai.com
shakersai.com
. It handles glowing effects, eerie lighting, and creatures of the night exceptionally well. It could fill the gap for scenes like “demonic altar ritual” or undead armies, which your current models (geared towards beauty and heroism) might not capture with the same vibe.

SDXL Refiner 1.0: Don’t forget the official SDXL Refiner model by Stability AI. While A1111 doesn’t natively chain base+refiner in one go, you can manually use the refiner in an img2img step. The refiner excels at fixing minor details at high resolution (especially faces, hands, and eyes)
videoproc.com
. For example, after your hires fix or at the Adetailer stage, you could load the refiner model and do a very low denoise pass. It’s often used at denoise 0.1–0.2 on 2048px images to put an extra layer of polish (skin pores, sharp edges, etc.). If you download it from HuggingFace (SDXL Refiner 1.0 weights), you can incorporate it when needed for that last 5% quality boost.

LoRAs: A few LoRAs commonly cited for fantasy that you might consider:

Armor/Clothing LoRAs: To generate highly accurate medieval or fantasy armor designs, look for LoRAs like “ArmorSentinel – Medieval Armor Style”
civitai.green
 or “Medieval Armour SDXL”. These can help if you find the base model isn’t nailing certain armor types (plate, chain, etc.). They usually come with trigger tags (e.g. <lora:ArmorSentinel:1> and prompting “ArmorSentinel style” or similar) – check the LoRA’s page. These LoRAs complement your Add-Detail LoRA by not just adding detail, but guiding the design of armor to historical or high-fantasy styles.

Creature LoRAs: For monsters, consider “SDXL Dragon Style” LoRA
reddit.com
 or “Fantasy Monsters XL” (there’s a pack on Tensor.art for D&D-style monsters
tensor.art
). A Dragon LoRA, for instance, can consistently enforce dragon-like anatomy and scaling. You’d invoke it with something like <lora:SDXLDragon:0.8> and perhaps use trigger words it suggests (some LoRAs have tags like “in the style of [name]” but many just work implicitly). These LoRAs are great to pair with DreamShaper or other creative models when making creatures – you get the imaginative rendering plus a guarantee the creature looks on-model (no random number of limbs).

Style LoRAs for Art: You might want a painterly style occasionally (e.g. a watercolor look, or a specific artist inspiration). LoRAs like “XL_moreArt” or “RealisticVision-XL Illustration” exist. One example: “Illusio ArtStyle XL” – not sure if that’s the exact name, but the community often shares LoRAs for turning outputs into concept art or oil paintings. If you find your images too photoreal for certain fantasy pieces, using a style LoRA (at maybe 0.8 strength) can instantly give you that illustrated feel. Mine the civitai forums or reddit for “favorite SDXL style LoRAs”
reddit.com
 – many users bundle small style LoRAs.

Facial Expression LoRAs: Since you do a lot of characters, a LoRA that targets facial expressions or poses can be useful. For SD1.5 there were “expression LoRAs” – not many for SDXL yet, but keep an eye out. One that does exist is “Epic Expressions XL” (if available) or even a LoRA for specific character types (e.g. a “female warrior pose” LoRA). These are less critical, but nice-to-haves when you want very specific looks that are hard to prompt.

Lens/Camera LoRAs: There are LoRAs to mimic certain camera lenses or film types (for ultra realism or cinematic effects). E.g., “85mm_portrait_XL” or “cinematicHDR_XL”. Rather than needing these, you can often just prompt those concepts (e.g. “85mm portrait photograph” does a lot already). But a dedicated LoRA could reinforce it. If you feel your portraits lack that DSLR touch, one of these could help.

Where to get: Most of these can be found on Civitai. For example, search “SDXL armor LoRA”, “SDXL dragon LoRA”, etc. Download links:

ArmorSentinel (Medieval Armor): Civitai link – focuses on realistic knight armor styles.

SDXL Dragon Style: Civitai link – helps with dragon features and consistency.

Fantasy Monsters Pack: Tensor.art link – a LoRA pack for various monsters.

MajicMix Fantasy (model, not LoRA): MajicMix XL is actually a model merge for vibrant fantasy art
shakersai.com
, so that’s another model to consider if you like colorful fantasy (download on Civitai).

Embeddings: The user already has an excellent set from StableYogi. If anything, they might add:

EasyNegative XL: If an SDXL-trained version of EasyNegative is available (there are community conversions), it’s a good all-purpose negative. It might overlap with what you have, but some people layer multiple negatives. (Civitai doesn’t have an official SDXL EasyNegative yet, but check the community forums for shared files).

Positive Style Embeddings: E.g. “AnalogDiffusionXL” (if someone made a TI to mimic Analog photography on SDXL) or “CinematicXL” embedding. These are less common since LoRAs have largely taken over style duties in SDXL. If you come across any well-reviewed textual inversions for SDXL (perhaps “ArcaneStyleXL” for a specific game’s style, etc.), they could be fun to experiment with. Just ensure they are meant for SDXL 1.0 and not SD1.5.

“BadPrompt XL”: There was a popular SD1.5 embedding called BadPrompt (and BadPrompt v2) that tackled a lot of unwanted artifacts. An SDXL version might exist. Using it in negatives could further clean generations. However, using too many negative embeddings can sometimes over-constrain the image (leading to “too safe/bland” results), so it’s a balance.

In summary, the user’s setup is already strong. The additions above can fill niche needs: Realism Engine and HelloWorld for more realism options, Nova or MajicMix for rich fantasy, and a few LoRAs for armor and monsters to really nail those genres. All are freely available (Civitai or HuggingFace). Make sure to check the licenses (most are CreativeML OpenRAIL or similar) and download the SDXL versions of each.

6. Workflow Optimization Tips

To get the most out of Automatic1111 with SDXL at 768x1344, plus Adetailer and upscaling, consider these best practices:

Hi-Res Fix vs Separate Upscaling: In your case, you generate at the relatively large base of 768×1344 already. That’s fine (SDXL can handle non-square aspect well, especially with high VRAM). Another approach is generating a bit smaller and using the built-in Hires fix. For example, generate at 512x896, then let Hires fix upscale 2× to 1024x1792. However, since you explicitly do a separate upscaling stage, you might keep Hires fix disabled in txt2img (as your JSON showed) and instead do manual img2img upscale. This gives more control. The key is: only upscale after applying Adetailer so that the face is fixed before blowing up the resolution (fixing small faces is easier on the smaller image, then they stay fixed when enlarged).

ADetailer usage: You’re already using Adetailer with a face detector (face_yolov8n.pt). One tip: consider switching to the slightly larger YOLO model face_yolov8s.pt for better detection on 768px images
reddit.com
. It can catch faces that the nano model might miss or better outline them (especially if your character is small in frame). In Adetailer settings, you might also enable it for “eyes” or “hands” with respective models if needed (there are YOLO models for hands as well). Given your focus on faces, you can keep it simple: one Adetailer pass on faces is usually enough. The settings you used (around 12 steps, denoise ~0.25) are good – they ensure the face is refined but not totally different. You can even increase Adetailer steps to ~20 if you find faces still lacking detail; just be cautious not to use too high denoise or the face might change identity. Also, the tip from the CyberRealistic author suggests “Mask only the top k largest” = 1 in Adetailer to only refine the primary face if multiple are present
diffus.me
 – this prevents it from wasting effort on tiny background faces in a crowd, for example.

Upscaling (ESRGAN vs Latent): For final 2× upscaling, you have two main methods: ESRGAN/realESRGAN upscalers (like 4x_UltraSharp, etc.) or Latent upscalers (using the SD model itself). Each has pros/cons:

ESRGAN (external) Upscalers: These are fast and excel at adding crispness. 4x-UltraSharp in particular is great for photoreal detail sharpening. With 24GB VRAM, you can often upscale the whole 768x1344 → 1536x2688 in one go with UltraSharp. If you encounter memory issues, use tiling. Tile size recommendation: With 24GB, try a tile of 1024×1024. That means the upscaler will process the image in chunks of 1024 px, which should be safe. You might even do 1344×1344 tile (so it halves only one dimension) since 4Mpx isn’t too high. If using A1111’s “GPU upscale” option, a 0.5x overlap is usually fine to avoid seams (so ~64px overlap on 1024 tile). Monitor VRAM – if usage is below your max, you could increase tile size further. The goal is to minimize seams while not OOMing. In practice, 512 tile is very conservative (for low VRAM cards); 1024 should be fine for you.

Latent Upscale: This uses the Stable Diffusion model to upscale (either via the Hires fix or via img2img with “latent (nearest)” or “latent (antialiased)” selected). Latent upscaling tends to preserve the artistic style and can add additional details since it actually re-generates with the model. It’s great if the ESRGAN output looks a bit too smooth or if you want the model to fill in more stuff. In your pipeline, you could do a small latent upscale (like 1.5× with some denoise ~0.3) before ESRGAN. In fact, your JSON’s upscale stage shows 15 steps at denoise 0.2 with UltraSharp – that indicates you did a hybrid: first 2× ESRGAN then 15 steps img2img on it. That’s a smart approach: ESRGAN gives resolution, then SD model polish with slight denoise. Continue that pattern. For when to use latent vs ESRGAN: If the image is already very detailed and you only need it bigger and a bit sharper (e.g., a photoreal portrait), ESRGAN-only is sufficient (and avoids any chance of generation changes). If the image could benefit from more detail or fixing (e.g., text or symbols that upscaler might blur, or you want more micro-detail on armor), doing a latent upscaling with the model will actually generate those new pixels in a learned way. It can also correct minor flaws (like slightly odd edges) because the model “re-draws” the image at higher res. Generally, latent upscalers maintain coherence better on things like faces (the SD model knows the face shape and will upscale it without introducing odd artifacts that ESRGAN might). However, latent upscaling can sometimes introduce new noise or alter textures. A good recipe is: Latent (antialiased) for 1.5× with denoise ~0.3, then ESRGAN for another ~1.33× to reach 2× total. The antialiased version of latent upscale helps avoid aliasing artifacts on diagonal lines and is recommended when upscaling drawings or crisp edges. For photoreal, the difference between “latent” and “latent (antialiased)” isn’t huge, but antialiased tends to produce a slightly cleaner upscale (less jaggies on fine lines).

Use cases: If final quality is paramount (e.g. you plan to print or share the image large), do a two-stage upscale: 1) Latent upscale by 1.5× with some denoise, 2) ESRGAN 4x-UltraSharp by ~1.33× (or just 2× if skipping latent). If speed is more important (for quick previews), a single ESRGAN 2× pass is fine.

Tiling for VRAM: As mentioned, with 24GB, you have a lot of freedom. You might only need to tile when using the most heavy 4× upscalers or if you try to upsize beyond 2×. If you ever want to do 4× upscale (1536x2688 → ~3072x5376), definitely use tiling (maybe 1024 or 1280 tiles). Also note A1111 now has a “Tiled Diffusion” and “Tiled VAE” feature which can be enabled to reduce memory usage during img2img upscales. Tiled VAE especially is useful for SDXL at big sizes – it loads only parts of the VAE at a time, lowering RAM hit. If you see high VRAM usage, try enabling “Enable VAE tiling” in settings when doing large hi-res img2img.

Memory/Performance Tweaks: Since you have plenty of VRAM, you can set --xformers for faster computation (if not already). Also, SDXL benefits from using clip skip 2 (as you did) for many finetunes – keep that for those models (Juggernaut and others explicitly mention using clip skip 2 for best results). If a particular model says use clip skip 1 (some merges do), follow that per model to avoid slight prompt misreads.

Prompting and CFG: SDXL models often work well with shorter prompts compared to SD1.5. You’re already using embeddings which include concepts like “masterpiece, best quality”, so you don’t need to spam those manually. It’s worth noting that extremely long prompts can sometimes confuse SDXL or lead to composition issues. Try to be concise yet descriptive. For example, instead of a paragraph of traits, break it into parts or use the Prompt editing UI to organize. The user is using a randomizer for environments and such, which is great. Keep an eye on how the matrix placeholders ([[environment]], etc.) combine – sometimes certain combos might produce odd results. If so, consider adding a negative like “disconnected, disjointed” or simply re-roll.

Aesthetic Gradient (optional): Automatic1111 has an “Aesthetic rating” feature (under the extra networks panel) which can apply an aesthetic score to guide the image (like making it more “beautiful” according to a learned metric). This requires a model or embedding for aesthetics. Some SDXL models (like Juggernaut) were trained with aesthetic scoring in mind. It’s not necessary, but if you find an “aesthetic embedding” (used in negative or positive to push towards artistically pleasing images), you could play with it. This is an advanced tweak – often the embeddings you have plus prompt and CFG tweaks do the job.

CFG Scale and Sampler: For SDXL, CFG ~6–8 is a good range (as you’ve used 6.1, 7.5 in examples). Photoreal models often do well around 5–7 CFG (to avoid overcooking), whereas more creative ones can handle a bit higher. If you see “washing out” or weird artifacts, sometimes lowering CFG helps. Sampler: DPM++ 2M Karras or SDE Karras are excellent choices for SDXL (they give stable results). You might try UniPC sampler as well – some report it’s both fast and high quality on SDXL. For final upscaling img2img, a sampler like DPM++ 2M or even Euler a (for a quick pass) works – but sticking to the same family (DPM++) is fine. Also, use Karras scheduler for initial generation if available (it was in your config) – it helps maintain consistency when changing steps. When doing hires fix or img2img, using the same sampler is generally recommended to preserve style. In Adetailer, you used DPM++ 2M as well (likely inherited). That’s good.

VRAM 24GB specific: You have the luxury to push resolution or batch size. If you ever want to generate multiple images at once (say a batch of 2 or 4), 24GB can handle 2 images at 768x1344 easily. This is useful for getting variations faster. However, note that when using Adetailer and upscaling, those will also then be applied to each image, so it will be sequential anyway. Still, you could do batch 2 for txt2img to get 2 candidates, then only Adetailer+upscale the one you like, for efficiency.

In short: Fix faces early (Adetailer at base size), then upscale carefully. Use latent upscale when you need the model’s touch, and ESRGAN for pure sharpening. Adjust tile size if needed, but 1024 is a good starting point for 2× on 24GB. And monitor how each stage affects the image – sometimes you may decide to skip the img2img refine if the ESRGAN output is already perfect, or vice versa.

7. Stage Configuration Summary

Bringing it all together, here’s a summary of recommended settings for each stage of your pipeline (txt2img → Adetailer → upscale), tuned for 24GB VRAM and the described use case:

Stage 1: txt2img (Initial Generation)

Resolution: 768×1344 (portrait orientation). Ensure Aspect Ratio is locked or set dimensions exactly.

Model: Choose based on subject (e.g. Juggernaut XL for photoreal characters, DreamShaper XL for fantastical scenes).

Prompt: Start with embeddings (e.g. <embedding:stable_yogis_pdxl_positives> <embedding:stable_yogis_realism_positives_v1>), then your scene/character description, then append LoRAs (e.g. <lora:CinematicStyle_v1:0.6> <lora:DetailedEyes_V3:0.8> etc. Use () to emphasize key traits and [] to de-emphasize if needed.

Negative Prompt: Include quality negatives and embeddings (blurry, low quality, <embedding:stable_yogis_pdxl_negatives2-neg>, <embedding:negative_hands>, ...). Basically your GLOBAL_BAD should expand to all relevant negatives.

Sampler: DPM++ 2M Karras (excellent balance for SDXL). Alternatively, DPM++ 2M SDE Karras works well too (SDE can sometimes give finer details).

Steps: ~30 steps is typically sufficient on SDXL
openlaboratory.ai
. You can go 40 for very complex prompts, but returns diminish past 30. (If using UniPC sampler, you might use 20–25 as it converges faster).

CFG Scale: 6 to 7.5. For photoreal models lean ~6; for more creative ones ~7–8. In your example, 7.5 was used with good results. Avoid extremely high CFG (>10) as SDXL can start ignoring prompt or causing artifacts
openlaboratory.ai
.

Clip Skip: 2 (for models known to benefit, like Juggernaut, RealismEngine, etc.). If you use a model that specifically says “use clip skip 1” (some do, check model notes), switch accordingly. Most merged models from SD1.5 heritage use clip2 though.

Batch size: 1 (since you’re focusing on one image at a time for max quality). You could do Batch 2 here if just exploring prompts, but for final, 1 is safer to not overuse VRAM needed for Adetailer/upscale.

Hires fix: Disabled (you will handle upscaling in a later stage manually).

Face Restoration: Disabled here (you will use Adetailer instead, which is more controlled than GFPGAN/Codeformer for this use case).

Seed: Use a fixed seed for reproducibility when fine-tuning prompt/LoRAs, or -1 for random if you want fresh variation each time. With your randomizer, seeds might be set per variant – that’s fine to leave random and rely on prompt matrix for diversity.

Stage 2: ADetailer (Face Refinement)
(This runs after the base image is generated, as an img2img on the face region.)

ADetailer Model (Detection): use face_yolov8n.pt or yolov8s for face detection. The small YOLOv8n is fast and worked for you; YOLOv8s might catch more if performance allows – either is okay.

ADetailer Target: Face (you can set it to target “face” and perhaps “eyes” if you have a second pass, but usually just face is enough).

Refinement Model: By default it uses the same model as Stage 1 (e.g. Juggernaut) to do the inpainting on the face. This is good because it keeps style consistent. (Optionally, you could specify a different checkpoint here if you found, say, SDXL Refiner or a specialized face model improved results, but testing is needed – Juggernaut itself is quite competent at faces).

Mask Settings: Typically “Mask blur” of 4–8 pixels is good so the blended area is smooth. “Only mask largest face = 1” as mentioned if multiple faces and you only care about the main one.

ADetailer Prompt: You can give it a focused prompt just for the face. E.g. “sharp detailed face, detailed eyes, perfect eyes, realistic skin”. You can also inject negative prompts specifically for face artifacts (“no smudged makeup, no blur”). In practice, if the overall prompt already contains what you want for the face, you can leave it and maybe just add a bit of emphasis. Since your base prompt likely already says “portrait, detailed skin, natural light”, those apply well. You did use ADetailer with probably the same prompt from the JSON. That’s okay, though sometimes adding a bit like “high detail, 8k face, symmetrical eyes” in Adetailer prompt helps.

ADetailer Sampler: Use the same sampler as base (DPM++ 2M Karras) for consistency.

ADetailer Steps: ~12 steps (as you used). You can go up to 20 for a slightly more refined outcome if needed. The detection/inpainting area is smaller than full image, so 12–20 is usually enough.

Denoising Strength: ~0.25 (you used ~0.26). This is a sweet spot: it allows new detail to form (pores, eye clarity) but keeps the original face identity ~75% intact. If faces are coming out too different, lower to 0.2. If they are still too similar to the flawed original (e.g. a slight blur remains), you can raise to 0.3. Try not to exceed 0.4 for faces or it may completely redraw it as a different person.

CFG Scale: around 5–6 (you used 6.0). Lower CFG here can sometimes help the inpainting be more subtle. 6 is fine because it’s not too high. If you notice any overshoot (like face gets over-detailed compared to rest of image), you could drop to 4 or 5. But usually 6 works to enforce your face prompt.

ADetailer LoRAs: If you had any LoRAs specifically for faces (e.g. a “eyes fixer” LoRA), you could apply them in this stage prompt at maybe slightly higher weight just for the face. In your case, DetailedEyes V3 is essentially doing that globally; it will definitely apply during Adetailer since it’s part of the model or prompt already. No need to change anything – it will naturally focus on eyes because you prompted for it and Adetailer is working on the face region.

Stage 3: Upscaling (Hires Img2Img + ESRGAN)

Upscaler Choice: Use R-ESRGAN 4x+ UltraSharp (the V2 or latest version). It produces very crisp, detailed results for photoreal images and also does well on CG/fantasy. In your config, you set 4x-UltraSharpV2 with upscale = 2.0. That implies A1111 took your 768x1344 to 1536x2688 by applying UltraSharp. Since UltraSharp is a 4× model, A1111 likely internally downscaled then upscaled to achieve 2× – which it handles automatically. So you can continue just setting 2× with that model.

Tiling: For 1536x2688 final, if memory is an issue, set “Tile width/height” in the extras tab (or in the script) to ~1024 and “Tile overlap” ~64. This ensures UltraSharp processes in chunks. If you haven’t encountered any VRAM errors so far, you might not even need tiling for 2×. But if you do a 4× sometime, definitely tile it.

After Upscale – Img2Img Refinement: You smartly do an img2img on the upscaled image with a small denoise. In your JSON, after UltraSharp 2×, you ran 15 steps at denoise 0.2 using (presumably) the base model. This is essentially a post-upscale latent refinement. Keep this practice:

Set “Upscale by” 2.0 and choose UltraSharp as upscaler.

In the sdweb UI (if using the script), also set “Denoising strength” ~0.2 and “Steps” ~15, Sampler same (DPM++ 2M).

This way, A1111 will first apply ESRGAN upscale, then use the SD model for 15 steps on the high-res result with 20% noise to clean/improve it. This often yields the best of both worlds: ESRGAN adds micro-details (sometimes a bit of oversharpening), and then the model smooths any artifacts and adds its learned detail where needed.

Ensure CFG during this is moderate (your upscale CFG was 7 in config or 6?). If not explicitly set, it might reuse txt2img’s CFG. Safer to set it around 6–7 again.

Clip skip should remain the same as earlier to maintain consistency.

Tile for Img2Img: If using the “Ultimate SD upscale” script or similar, you might have separate tiling for the model pass too. But with 24GB, you likely can do the 1536x2688 model refinement in one go (especially at only 15 steps). If not, you could tile that as well, but it’s usually fine.

Alternate approach: Instead of ESRGAN first, you could do the model img2img first (latent upscale 1.5× or 2×) then ESRGAN after. Both orders are valid. The order you used (ESRGAN then model) gives a slightly cleaner outcome (model fixes any ESRGAN artifacts). The reverse (model then ESRGAN) might yield a slightly more detailed but also slightly more artificially sharpened look. Feel free to experiment which you prefer – but your current pipeline seems to be working great.

Stage 4 (Optional): SDXL Refiner or Additional Fixes
This is not in your original pipeline, but if perfection is required: after Stage 3, you could load the SDXL Refiner model and do one pass at denoise 0.1 just on the final image. For example, take the 1536x2688, set Refiner model, do 5–10 steps at CFG 5, denoise 0.1 with prompt = original prompt. This often will very subtly enhance things like eyes or remove minor blur. It’s a gentle touch – not a big difference, so it’s optional. It might smooth some oversharpening from UltraSharp if any remains. Because it’s subtle, you usually don’t need to tile that either. If you do this, remember to remove any LoRA that the refiner can’t handle (refiner is trained differently – though some say you can still use LoRAs, results may vary). It may be safest to refiner-pass without LoRAs, just pure model on final image.

Finally, here is an example configuration summary for a typical run (as an illustration):

Txt2Img: 30 steps, DPM++ 2M Karras, CFG 7, seed -1, size 768×1344, clip skip 2.
Prompt: "<embedding:stable_yogis_pdxl_positives> <embedding:stable_yogis_realism_positives_v1> (masterpiece, best quality), high fantasy battle scene, two armored knights dueling on castle walls at sunset, dramatic lighting, detailed environment <lora:CinematicStyle_v1:0.7> <lora:Add-Detail-XL:0.6>"
Negative: "blurry, bad anatomy, distorted, extra limbs, <embedding:stable_yogis_pdxl_negatives2-neg>, <embedding:stable_yogis_anatomy_negatives_v1-neg>, <embedding:negative_hands>, <embedding:sdxl_cyberrealistic_simpleneg-neg>".

ADetailer (Face): Enabled (after txt2img). Detector: YOLOv8 face. Inpaint model: same as base.
Face prompt: "detailed face, sharp eyes, no distortions" (or reuse main prompt if faces were already detailed).
Steps: 15, Sampler: DPM++2M, Denoise: 0.25, CFG: 5.5.

Upscale: Upscaler: 4x-UltraSharp, Scale: 2.0, Tile disabled (for this size, if VRAM OK).
After upscale, Img2img on result: 15 steps, DPM++2M, Denoise: 0.2, CFG: 6, using base model (clip skip 2). (This is configured in A1111 by setting those values in the hires fix or script section – as you did via the JSON).
Resulting image: 1536×2688px.

This yields a final high-res image with faces fixed and enhanced, and overall quality boosted. Use case adjustments: If you were doing a solo character portrait instead of a scene, you might adjust the above by increasing Adetailer emphasis (maybe two passes: one for face, one for eyes) and perhaps doing only 1.5× upscale instead of 2× (because close-up faces at too high res can show flaws). For a complex scene with many elements, you might favor model-based upscaling (latent) to add detail everywhere.

By following these stage-wise settings and tips, you can reliably produce epic fantasy art that is not only visually stunning but also technically sound (anatomically correct, high-detail, and cohesive). Enjoy crafting those images – with these tools and configurations, you’re set up for success! 
openlaboratory.ai
diffus.me