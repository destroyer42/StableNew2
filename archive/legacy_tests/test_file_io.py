"""Test file I/O utilities"""

from src.utils.file_io import get_safe_filename, read_prompt_pack, read_text_file, write_text_file


class TestFileIO:
    def test_read_prompt_pack_txt_format(self, tmp_path):
        """Test reading .txt format prompt pack"""
        pack_content = """beautiful landscape, mountains, lakes
(masterpiece, best quality) natural scenery
neg: blurry, low quality, artificial

portrait of elegant woman, professional photography
studio lighting, high resolution, detailed
neg: cartoon, anime, distorted"""

        pack_file = tmp_path / "test_pack.txt"
        pack_file.write_text(pack_content, encoding="utf-8")

        prompts = read_prompt_pack(pack_file)

        assert len(prompts) == 2
        assert (
            prompts[0]["positive"]
            == "beautiful landscape, mountains, lakes (masterpiece, best quality) natural scenery"
        )
        assert prompts[0]["negative"] == "blurry, low quality, artificial"
        assert (
            prompts[1]["positive"]
            == "portrait of elegant woman, professional photography studio lighting, high resolution, detailed"
        )
        assert prompts[1]["negative"] == "cartoon, anime, distorted"

    def test_get_safe_filename(self):
        """Test safe filename generation"""
        # Test invalid characters
        unsafe_name = 'test<>:"/\\|?*file.txt'
        safe_name = get_safe_filename(unsafe_name)
        assert safe_name == "test___________file.txt"

        # Test long filename
        long_name = "a" * 300
        safe_name = get_safe_filename(long_name)
        assert len(safe_name) <= 200

        # Test empty filename
        empty_name = ""
        safe_name = get_safe_filename(empty_name)
        assert safe_name == "unnamed"

        # Test normal filename
        normal_name = "valid_filename.txt"
        safe_name = get_safe_filename(normal_name)
        assert safe_name == normal_name


import base64
from io import BytesIO

from PIL import Image

from src.utils import load_image_to_base64, read_text_file, save_image_from_base64, write_text_file


class TestFileIO:
    """Test cases for file I/O utilities"""

    def create_test_image_base64(self):
        """Helper to create a test image as base64"""
        img = Image.new("RGB", (100, 100), color="red")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def test_save_image_from_base64(self, tmp_path):
        """Test saving base64 image to file"""
        img_base64 = self.create_test_image_base64()
        output_path = tmp_path / "test_image.png"

        assert save_image_from_base64(img_base64, output_path) is True
        assert output_path.exists()

        # Verify it's a valid image
        img = Image.open(output_path)
        assert img.size == (100, 100)

    def test_save_image_creates_parent_dirs(self, tmp_path):
        """Test that parent directories are created"""
        img_base64 = self.create_test_image_base64()
        output_path = tmp_path / "subdir" / "test_image.png"

        assert save_image_from_base64(img_base64, output_path) is True
        assert output_path.exists()

    def test_save_image_with_data_url_prefix(self, tmp_path):
        """Test saving image with data URL prefix"""
        img_base64 = self.create_test_image_base64()
        data_url = f"data:image/png;base64,{img_base64}"
        output_path = tmp_path / "test_image.png"

        assert save_image_from_base64(data_url, output_path) is True
        assert output_path.exists()

    def test_load_image_to_base64(self, tmp_path):
        """Test loading image to base64"""
        # Create a test image
        img = Image.new("RGB", (50, 50), color="blue")
        image_path = tmp_path / "test.png"
        img.save(image_path)

        # Load to base64
        result = load_image_to_base64(image_path)
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

        # Verify we can decode it back
        img_data = base64.b64decode(result)
        loaded_img = Image.open(BytesIO(img_data))
        assert loaded_img.size == (50, 50)

    def test_load_nonexistent_image(self, tmp_path):
        """Test loading non-existent image"""
        result = load_image_to_base64(tmp_path / "nonexistent.png")
        assert result is None

    def test_read_text_file(self, tmp_path):
        """Test reading text file with UTF-8"""
        test_content = "Hello World\n日本語テキスト\nDeutsch"
        file_path = tmp_path / "test.txt"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(test_content)

        result = read_text_file(file_path)
        assert result == test_content

    def test_write_text_file(self, tmp_path):
        """Test writing text file with UTF-8"""
        test_content = "Test content\n中文内容\nKorean: 한국어"
        file_path = tmp_path / "output.txt"

        assert write_text_file(file_path, test_content) is True
        assert file_path.exists()

        # Verify content
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        assert content == test_content

    def test_write_text_creates_parent_dirs(self, tmp_path):
        """Test that parent directories are created"""
        file_path = tmp_path / "subdir" / "output.txt"

        assert write_text_file(file_path, "test") is True
        assert file_path.exists()

    def test_utf8_roundtrip(self, tmp_path):
        """Test UTF-8 encoding roundtrip"""
        test_content = "Mixed: Hello, こんにちは, 你好, مرحبا, Привет"
        file_path = tmp_path / "utf8_test.txt"

        # Write
        assert write_text_file(file_path, test_content) is True

        # Read
        result = read_text_file(file_path)
        assert result == test_content
