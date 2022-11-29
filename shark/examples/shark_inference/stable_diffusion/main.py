from transformers import CLIPTextModel, CLIPTokenizer
import torch
from PIL import Image
from diffusers import (
    LMSDiscreteScheduler,
    PNDMScheduler,
    DDIMScheduler,
    DPMSolverMultistepScheduler,
)
from tqdm.auto import tqdm
import numpy as np
from stable_args import args
from utils import get_shark_model, set_iree_runtime_flags
from opt_params import get_unet, get_vae, get_clip
import time
from model_wrappers import get_vae_mlir


# Helper function to profile the vulkan device.
def start_profiling(file_path="foo.rdc", profiling_mode="queue"):
    if args.vulkan_debug_utils and "vulkan" in args.device:
        import iree

        print(f"Profiling and saving to {file_path}.")
        vulkan_device = iree.runtime.get_device(args.device)
        vulkan_device.begin_profiling(mode=profiling_mode, file_path=file_path)
        return vulkan_device
    return None


def end_profiling(device):
    if device:
        return device.end_profiling()


if __name__ == "__main__":

    dtype = torch.float32 if args.precision == "fp32" else torch.half

    prompt = args.prompts
    height = 512  # default height of Stable Diffusion
    width = 512  # default width of Stable Diffusion
    if args.version == "v2":
        height = 768
        width = 768

    num_inference_steps = args.steps  # Number of denoising steps

    # Scale for classifier-free guidance
    guidance_scale = torch.tensor(args.guidance_scale).to(torch.float32)

    generator = torch.manual_seed(
        args.seed
    )  # Seed generator to create the inital latent noise

    batch_size = len(prompt)

    set_iree_runtime_flags()
    unet = get_unet()
    vae = get_vae()
    clip = get_clip()

    tokenizer = CLIPTokenizer.from_pretrained("openai/clip-vit-large-patch14")
    scheduler = DPMSolverMultistepScheduler.from_pretrained(
        "CompVis/stable-diffusion-v1-4",
        subfolder="scheduler",
    )
    if args.version == "v2":
        tokenizer = CLIPTokenizer.from_pretrained(
            "stabilityai/stable-diffusion-2", subfolder="tokenizer"
        )

        scheduler = DPMSolverMultistepScheduler.from_pretrained(
            "stabilityai/stable-diffusion-2",
            subfolder="scheduler",
        )

    start = time.time()

    text_input = tokenizer(
        prompt,
        padding="max_length",
        max_length=args.max_length,
        truncation=True,
        return_tensors="pt",
    )

    text_embeddings = clip.forward((text_input.input_ids,))
    text_embeddings = torch.from_numpy(text_embeddings).to(dtype)
    max_length = text_input.input_ids.shape[-1]
    uncond_input = tokenizer(
        [""] * batch_size,
        padding="max_length",
        max_length=max_length,
        return_tensors="pt",
    )
    uncond_embeddings = clip.forward((uncond_input.input_ids,))
    uncond_embeddings = torch.from_numpy(uncond_embeddings).to(dtype)

    text_embeddings = torch.cat([uncond_embeddings, text_embeddings])

    latents = torch.randn(
        (batch_size, 4, height // 8, width // 8),
        generator=generator,
        dtype=torch.float32,
    ).to(dtype)

    scheduler.set_timesteps(num_inference_steps)
    scheduler.is_scale_input_called = True

    latents = latents * scheduler.init_noise_sigma
    text_embeddings_numpy = text_embeddings.detach().numpy()
    avg_ms = 0

    for i, t in tqdm(enumerate(scheduler.timesteps)):
        step_start = time.time()
        print(f"i = {i} t = {t}", end="")
        timestep = torch.tensor([t]).to(dtype).detach().numpy()
        latent_model_input = scheduler.scale_model_input(latents, t)
        latents_numpy = latent_model_input.detach().numpy()

        profile_device = start_profiling(file_path="unet.rdc")

        noise_pred = unet.forward(
            (
                latents_numpy,
                timestep,
                text_embeddings_numpy,
                guidance_scale,
            )
        )

        end_profiling(profile_device)

        noise_pred = torch.from_numpy(noise_pred)
        step_time = time.time() - step_start
        avg_ms += step_time
        step_ms = int((step_time) * 1000)
        print(f" ({step_ms}ms)")

        latents = scheduler.step(noise_pred, t, latents).prev_sample

    avg_ms = 1000 * avg_ms / args.steps
    print(f"Average step time: {avg_ms}ms/it")

    # scale and decode the image latents with vae
    latents = 1 / 0.18215 * latents
    latents_numpy = latents.detach().numpy()
    profile_device = start_profiling(file_path="vae.rdc")
    image = vae.forward((latents_numpy,))
    end_profiling(profile_device)
    image = torch.from_numpy(image)
    image = image.detach().cpu().permute(0, 2, 3, 1).numpy()
    images = (image * 255).round().astype("uint8")

    print("Total image generation runtime (s): {}".format(time.time() - start))

    pil_images = [Image.fromarray(image) for image in images]
    for i in range(batch_size):
        pil_images[i].save(f"{args.prompts[i]}_{i}.jpg")
