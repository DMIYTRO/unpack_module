from classifier import classify_face_back

files = ['1.tif']
print(classify_face_back(files))

files = ['зворот.tif', 'лице.tif']
print(classify_face_back(files))
