import os
from sys import executable
import subprocess
from apps.stable_diffusion.src.utils.resources import (
    get_json_file,
)
from datetime import datetime as dt
from shark.shark_downloader import download_public_file
from image_comparison import compare_images
import argparse
from glob import glob
import shutil

model_config_dicts = get_json_file(
    os.path.join(
        os.getcwd(),
        "apps/stable_diffusion/src/utils/resources/model_config.json",
    )
)


def test_loop(device="vulkan", beta=False, extra_flags=[]):
    # Get golden values from tank
    shutil.rmtree("./test_images", ignore_errors=True)
    os.mkdir("./test_images")
    os.mkdir("./test_images/golden")
    hf_model_names = model_config_dicts[0].values()
    tuned_options = ["--no-use_tuned", "--use_tuned"]
    import_options = ["--import_mlir", "--no-import_mlir"]
    prompt_text = "--prompt=cyberpunk forest by Salvador Dali"
    if os.name == 'nt':
        prompt_text ='--prompt="cyberpunk forest by Salvador Dali"',

    if beta:
        extra_flags.append("--beta_models=True")
    for import_opt in import_options:
        for model_name in hf_model_names:
            for use_tune in tuned_options:
                command = [
                    executable,  # executable is the python from the venv used to run this
                    "apps/stable_diffusion/scripts/txt2img.py",
                    "--device=" + device,
                    prompt_text,
                    "--negative_prompts=" + '""',
                    "--seed=42",
                    import_opt,
                    "--output_dir="
                    + os.path.join(os.getcwd(), "test_images", model_name),
                    "--hf_model_id=" + model_name,
                    use_tune,
                ]
                command += extra_flags
                if os.name == "nt":
                    command = " ".join(command)
                generated_image = not subprocess.call(
                    command, stdout=subprocess.DEVNULL
                )
                if os.name != "nt":
                    command = " ".join(command)
                if generated_image:
                    print(command)
                    print("Successfully generated image")
                    os.makedirs(
                        "./test_images/golden/" + model_name, exist_ok=True
                    )
                    download_public_file(
                        "gs://shark_tank/testdata/golden/" + model_name,
                        "./test_images/golden/" + model_name,
                    )
                    test_file_path = os.path.join(
                        os.getcwd(),
                        "test_images",
                        model_name,
                        "generated_imgs",
                        dt.now().strftime("%Y%m%d"),
                        "*.png",
                    )
                    test_file = glob(test_file_path)[0]

                    golden_path = (
                        "./test_images/golden/" + model_name + "/*.png"
                    )
                    golden_file = glob(golden_path)[0]
                    compare_images(test_file, golden_file)
                else:
                    print(command)
                    print("failed to generate image for this configuration")
                    if "2_1_base" in model_name:
                        print("failed a known successful model.")
                        exit(1)


parser = argparse.ArgumentParser()

parser.add_argument("-d", "--device", default="vulkan")
parser.add_argument(
    "-b", "--beta", action=argparse.BooleanOptionalAction, default=False
)


if __name__ == "__main__":
    args = parser.parse_args()
    print(args)
    test_loop(args.device, args.beta, [])
